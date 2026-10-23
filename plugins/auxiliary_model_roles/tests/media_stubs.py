"""Host stand-ins for the media-embedding tests: plugin config, providers, keys, HTTP and a FAISS-like store."""

import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import types
from enum import Enum
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "usr.plugins.auxiliary_model_roles"
PROVIDERS = {
    "llama_cpp": {"litellm_provider": "hosted_vllm", "kwargs": {"api_base": "http://host.docker.internal:8080/v1", "api_key": "llama-cpp"}},
    "openrouter": {"litellm_provider": "openai", "kwargs": {"api_base": "https://openrouter.ai/api/v1", "extra_headers": {"X-Title": "Agent Zero"}}},
    "huggingface": {"litellm_provider": "huggingface"},
    "other": {"litellm_provider": "openai"},
    "openai": {"litellm_provider": "openai"},
}


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeHttp:
    """Records requests; answers with a vector derived from each item's first part type."""

    def __init__(self):
        self.requests, self.status, self.error, self.vectors = [], 200, None, {}

    def vector_for(self, parts):
        kind = parts[0]["type"]
        return self.vectors.get(kind, [3.0, 4.0, 0.0])

    def client(self, timeout=None):
        http = self

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, headers=None):
                http.requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
                if http.error:
                    raise http.error
                if http.status >= 400:
                    return FakeResponse(http.status, {"error": {"message": "media not supported"}})
                data = [{"index": i, "embedding": http.vector_for(item["content"])} for i, item in enumerate(json["input"])]
                return FakeResponse(200, {"data": list(reversed(data))})
        return Client()


class HostStubs:
    def __init__(self, config=None, keys=None, base=None):
        self.config = config if config is not None else {"embedding": {"models": {}}}
        self.keys = keys or {}
        self.base = base
        self.http = FakeHttp()
        self.embedding_cfg = {"provider": "llama_cpp", "name": "embeddinggemma-2", "api_base": "", "kwargs": {}}

    def modules(self):
        helpers = types.ModuleType("helpers")
        helpers.plugins = types.SimpleNamespace(get_plugin_config=lambda _name, _agent=None: self.config)
        helpers.files = types.SimpleNamespace(get_abs_path=lambda *parts: os.path.join(self.base or "", *parts))
        providers = types.ModuleType("helpers.providers")
        providers.get_provider_config = lambda kind, name: PROVIDERS.get(name)
        models = types.ModuleType("models")
        models.get_api_key = lambda name: self.keys.get(name, "None")
        httpx = types.ModuleType("httpx")
        httpx.AsyncClient = self.http.client
        httpx.HTTPError = type("HTTPError", (Exception,), {})
        model_config = types.ModuleType("plugins._model_config.helpers.model_config")
        model_config.get_embedding_model_config = lambda agent=None: dict(self.embedding_cfg)
        packages = {name: types.ModuleType(name) for name in (
            "plugins", "plugins._model_config", "plugins._model_config.helpers", "usr", "usr.plugins",
            PACKAGE, PACKAGE + ".helpers")}
        return {"helpers": helpers, "helpers.plugins": helpers.plugins, "helpers.files": helpers.files,
                "helpers.providers": providers, "models": models, "httpx": httpx,
                model_config.__name__: model_config, **packages}

    def start(self):
        self.patcher = patch.dict(sys.modules, self.modules())
        self.patcher.start()
        return self

    def stop(self):
        self.patcher.stop()

    def load(self, relative, name):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


class FakeIndex:
    def __init__(self, d):
        self.d, self.rows = d, []

    @property
    def ntotal(self):
        return len(self.rows)

    def reconstruct(self, position):
        return list(self.rows[position])


class FakeFaiss:
    """The slice of LangChain FAISS that media memory uses, with inner-product scores."""

    def __init__(self, d=3):
        self.index = FakeIndex(d)
        self.docstore = types.SimpleNamespace(_dict={})
        self.index_to_docstore_id = {}

    def add_embeddings(self, text_embeddings, metadatas=None, ids=None):
        for (text, vector), meta, doc_id in zip(text_embeddings, metadatas, ids):
            self.index_to_docstore_id[len(self.index.rows)] = doc_id
            self.index.rows.append(list(vector))
            self.docstore._dict[doc_id] = types.SimpleNamespace(page_content=text, metadata=dict(meta))

    def add_text(self, doc_id, text, vector, meta):
        self.add_embeddings([(text, vector)], [meta], [doc_id])

    def delete(self, ids):
        keep = [(i, doc_id) for i, doc_id in sorted(self.index_to_docstore_id.items()) if doc_id not in ids]
        rows = [self.index.rows[i] for i, _ in keep]
        self.index.rows = rows
        self.index_to_docstore_id = {n: doc_id for n, (_, doc_id) in enumerate(keep)}
        for doc_id in ids:
            self.docstore._dict.pop(doc_id, None)

    async def asimilarity_search_with_score_by_vector(self, vector, k=4, filter=None):
        scored = []
        for position, doc_id in self.index_to_docstore_id.items():
            doc = self.docstore._dict[doc_id]
            if filter and not filter(doc.metadata):
                continue
            row = self.index.rows[position]
            scored.append((doc, sum(a * b for a, b in zip(row, vector))))
        return sorted(scored, key=lambda pair: -pair[1])[:k]


class MemoryArea(Enum):
    MAIN = "main"
    FRAGMENTS = "fragments"
    SOLUTIONS = "solutions"


class FakeMemory:
    """Stands in for plugins._memory.helpers.memory with one database per test."""

    def __init__(self, db_dir, d=3, knowledge=None):
        self.db = FakeFaiss(d)
        self.db_dir = db_dir
        self.knowledge = knowledge or {}
        self.saved = 0
        memory = self
        counter = iter(range(1, 10_000))

        class Wrap:
            memory_subdir = "default"
            db = memory.db

            def _generate_doc_id(self):
                return f"m{next(counter)}"

            def _save_db(self):
                memory.saved += 1

        class Memory:
            Area = MemoryArea

            @staticmethod
            async def get(agent):
                return Wrap()

            @staticmethod
            def get_timestamp():
                return "2026-10-22T00:00:00"

            @staticmethod
            def _get_comparator(condition):
                return lambda data: data.get("area") == condition

            @staticmethod
            def _cosine_normalizer(val):
                return max(0.0, min(1.0, (1 + val) / 2))

        self.module = types.ModuleType("plugins._memory.helpers.memory")
        self.module.Memory = Memory
        self.module.abs_db_dir = lambda subdir: self.db_dir
        self.module.abs_knowledge_dir = lambda subdir, *parts: os.path.join(self.knowledge.get(subdir, "/missing"), *parts)
        self.module.get_knowledge_subdirs_by_memory_subdir = lambda subdir, default: default

    def marker(self, provider="llama_cpp", name="embeddinggemma-2"):
        with open(os.path.join(self.db_dir, "embedding.json"), "w", encoding="utf-8") as handle:
            json.dump({"model_provider": provider, "model_name": name}, handle)


def unit(vector):
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]
