"""Representative model-list payloads of local inference servers, as route tables for FakeEndpoint.

Shapes come from each project's documentation/source and the owner's router notes, not from live output;
the parsers are tolerant and tests pin only the fields they rely on. Router rows carry deliberately
secret-looking command lines (SECRET_MARKER) to prove they are never forwarded.
"""
from __future__ import annotations

SECRET_MARKER = "SECRET-DO-NOT-LEAK"


def _list(rows, **extra):
    return {"object": "list", "data": rows, **extra}


# ---------------------------------------------------------------- llama.cpp
def llamacpp_router_rows():
    return [
        {"id": "qwen38-27b-apex-mini", "object": "model", "owned_by": "llamacpp", "aliases": ["qwen38-mini"], "tags": ["text"],
         "status": {"value": "loaded",
                    "args": ["llama-server", "--ctx-size", "131072", "--api-key", SECRET_MARKER],
                    "preset": f"[qwen38-27b-apex-mini]\nctx-size = 131072\nmodel = /models/qwen.gguf\napi-key = {SECRET_MARKER}"}},
        {"id": "qwen38-27b-apex-mini-vision", "object": "model", "owned_by": "llamacpp", "aliases": [], "tags": ["vision"],
         "status": {"value": "unloaded",
                    "args": ["llama-server", "-c", "81920", "--mmproj", "/models/mm.gguf", "--api-key", SECRET_MARKER],
                    "preset": f"[qwen38-27b-apex-mini-vision]\nctx-size = 81920\nmmproj = /models/mm.gguf\napi-key = {SECRET_MARKER}"}},
        {"id": "ornith-1.5-35b-gpukv-128k-vision", "object": "model", "owned_by": "llamacpp", "aliases": [], "tags": [],
         "status": {"value": "sleeping", "args": ["llama-server", "--ctx-size", "32768"], "preset": "ctx-size = 32768"}},
        {"id": "gemma-4-12b-qat", "object": "model", "owned_by": "llamacpp", "aliases": [], "tags": [],
         "status": {"value": "downloading"}},
        {"id": "half-downloaded-model", "object": "model", "owned_by": "llamacpp", "aliases": [], "tags": [],
         "status": {"value": "incomplete"}},
        {"id": "crashing-config", "object": "model", "owned_by": "llamacpp", "aliases": [], "tags": [],
         "status": {"value": "unloaded", "failed": True, "exit_code": 1}},
        # names the host's chat filter drops (embed / image) although the router serves them as plain rows
        {"id": "qwen3-embedding-0.6b", "object": "model", "owned_by": "llamacpp", "aliases": [], "tags": ["embedding"],
         "status": {"value": "unloaded"}},
        {"id": "qwen-image-edit-2509-q4", "object": "model", "owned_by": "llamacpp", "aliases": [], "tags": [],
         "status": {"value": "unloaded"}},
    ]


def llamacpp_router():
    rows = _list(llamacpp_router_rows())
    return {"/v1/models": rows, "/models": rows, "/props": {"role": "router"}, "/health": {"status": "ok"}}


def llamacpp_single():
    row = {"id": "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf", "object": "model", "owned_by": "llamacpp",
           "meta": {"n_ctx_train": 131072}, "architecture": {"input_modalities": ["text", "image"]}}
    return {"/v1/models": _list([row]),
            "/props": {"default_generation_settings": {"n_ctx": 65536}, "modalities": {"vision": True}, "is_sleeping": False}}


# ---------------------------------------------------------------- LM Studio
def lmstudio():
    v1 = {"models": [
        {"type": "llm", "key": "qwen/qwen3-30b-a3b", "display_name": "Qwen3 30B A3B", "format": "gguf",
         "quantization": {"name": "Q4_K_M"}, "max_context_length": 262144,
         "loaded_instances": [{"id": "qwen/qwen3-30b-a3b", "config": {"context_length": 32768}}],
         "capabilities": {"vision": False, "trained_for_tool_use": True}},
        {"type": "llm", "key": "google/gemma-3-12b", "display_name": "Gemma 3 12B", "format": "gguf",
         "quantization": {"name": "Q4_0"}, "max_context_length": 131072, "loaded_instances": [],
         "capabilities": {"vision": True}},
        {"type": "embedding", "key": "text-embedding-nomic-embed-text-v1.5", "display_name": "Nomic Embed", "format": "gguf",
         "max_context_length": 2048, "loaded_instances": []},
    ]}
    v0 = _list([
        {"id": "qwen/qwen3-30b-a3b", "object": "model", "type": "llm", "state": "loaded", "quantization": "Q4_K_M",
         "max_context_length": 262144, "loaded_context_length": 32768},
        {"id": "google/gemma-3-12b", "object": "model", "type": "vlm", "state": "not-loaded", "quantization": "Q4_0",
         "max_context_length": 131072},
        {"id": "text-embedding-nomic-embed-text-v1.5", "object": "model", "type": "embeddings", "state": "not-loaded",
         "max_context_length": 2048},
    ])
    openai = _list([
        {"id": "qwen/qwen3-30b-a3b", "object": "model", "owned_by": "organization_owner"},
        {"id": "google/gemma-3-12b", "object": "model", "owned_by": "organization_owner"},
        {"id": "text-embedding-nomic-embed-text-v1.5", "object": "model", "owned_by": "organization_owner"},
    ])
    return {"/api/v1/models": v1, "/api/v0/models": v0, "/v1/models": openai}


def lmstudio_legacy():
    """LM Studio 0.3.x: no /api/v1/models, only the v0 REST API and the OpenAI list."""
    routes = lmstudio()
    routes.pop("/api/v1/models")
    return routes


# ---------------------------------------------------------------- Ollama
def ollama():
    tags = {"models": [
        {"name": "llama3.1:8b", "model": "llama3.1:8b", "digest": "sha256:aaa",
         "details": {"family": "llama", "parameter_size": "8.0B", "quantization_level": "Q4_K_M"}},
        {"name": "llama3.1:8b-instruct-q8_0", "model": "llama3.1:8b-instruct-q8_0", "digest": "sha256:aaa",
         "details": {"family": "llama", "parameter_size": "8.0B", "quantization_level": "Q8_0"}},
        {"name": "nomic-embed-text:latest", "model": "nomic-embed-text:latest", "digest": "sha256:bbb",
         "details": {"family": "nomic-bert", "parameter_size": "137M", "quantization_level": "F16"}},
    ]}
    ps = {"models": [{"name": "llama3.1:8b", "model": "llama3.1:8b", "size": 6_000_000_000, "context_length": 8192}]}
    openai = _list([{"id": "llama3.1:8b", "object": "model", "owned_by": "library"},
                    {"id": "llama3.1:8b-instruct-q8_0", "object": "model", "owned_by": "library"},
                    {"id": "nomic-embed-text:latest", "object": "model", "owned_by": "library"}])
    return {"/api/tags": tags, "/api/ps": ps, "/v1/models": openai}


# ---------------------------------------------------------------- llama-swap
def llama_swap():
    rows = _list([
        {"id": "qwen-fast", "object": "model", "owned_by": "llama-swap", "name": "Qwen fast", "status": {"value": "ready"},
         "context_length": 32768, "meta": {"llamaswap": {"type": "llm", "aliases": ["gpt-4o-mini"]}}},
        {"id": "gemma-vision", "object": "model", "owned_by": "llama-swap", "name": "Gemma vision", "status": {"value": "stopped"},
         "capabilities": ["vision"], "meta": {"llamaswap": {"type": "llm", "aliases": []}}},
        {"id": "bge-embed", "object": "model", "owned_by": "llama-swap", "name": "BGE", "status": {"value": "stopped"},
         "meta": {"llamaswap": {"type": "embedding", "aliases": []}}},
    ])
    return {"/v1/models": rows, "/running": {"running": [{"model": "qwen-fast", "state": "ready"}]}}


# ---------------------------------------------------------------- Unsloth Studio
def unsloth():
    rows = _list([
        {"id": "unsloth/Qwen3-8B-GGUF:Q4_K_XL", "object": "model", "loaded": True, "status": {"value": "loaded"},
         "quant": "Q4_K_XL", "context_length": 32768, "max_context_length": 40960, "task": "chat"},
        {"id": "my-qwen-alias", "object": "model", "loaded": False, "status": {"value": "unloaded"},
         "quant": "Q8_0", "max_context_length": 40960, "task": "chat"},
        {"id": "unsloth/embeddinggemma-300m", "object": "model", "loaded": False, "status": {"value": "unloaded"},
         "task": "embedding"},
    ])
    return {"/v1/models": rows}


# ---------------------------------------------------------------- Strata Router (owner's router)
STRATA_VISION_160K = "qwen3.8-flash-next-iq3_xxs-strata-mtp-vision-160k"


def strata_router():
    rows = _list([
        {"id": "qwen3.8-flash-next-iq3_xxs-strata-mtp-vision-128k", "object": "model", "owned_by": "strata-router",
         "context_length": 130560, "supports_vision": True},
        {"id": "qwen3.8-flash-next-iq3_xxs-strata-mtp-text-128k", "object": "model", "owned_by": "strata-router",
         "context_length": 130560, "supports_vision": False},
        {"id": STRATA_VISION_160K, "object": "model", "owned_by": "strata-router",
         "context_length": 163328, "supports_vision": True},
    ])
    status = {"models": [
        {"id": "qwen3.8-flash-next-iq3_xxs-strata-mtp-vision-128k", "context": 131072, "client_context": 130560, "vision": True, "loaded": False},
        {"id": "qwen3.8-flash-next-iq3_xxs-strata-mtp-text-128k", "context": 131072, "client_context": 130560, "vision": False, "loaded": False},
        {"id": STRATA_VISION_160K, "context": 163840, "client_context": 163328, "vision": True, "loaded": True},
    ]}
    return {"/v1/models": rows, "/status": status, "/health": status}


# ---------------------------------------------------------------- generic OpenAI-compatible
def openai_generic():
    return {"/v1/models": _list([
        {"id": "my-served-model", "object": "model", "owned_by": "vllm", "max_model_len": 32768},
        {"id": "another-model", "object": "model", "owned_by": "vllm"},
    ])}


def openai_generic_without_v1():
    """Server whose list lives at /models (no /v1 prefix), like the host's generic fallback expects."""
    routes = openai_generic()
    return {"/models": routes["/v1/models"]}


KINDS = {
    "llamacpp_router": llamacpp_router,
    "llamacpp_single": llamacpp_single,
    "lmstudio": lmstudio,
    "lmstudio_legacy": lmstudio_legacy,
    "ollama": ollama,
    "llama_swap": llama_swap,
    "unsloth": unsloth,
    "strata_router": strata_router,
    "openai_generic": openai_generic,
}
