"""Run the PINNED upstream Agent Zero model_search.py (v2.11 / v2.14) outside Agent Zero.

The handler's host imports are stubbed exactly as far as it uses them: ApiHandler, get_provider_config
(backed by the pinned conf/model_providers.yaml) and models.get_api_key (env keys only, "None" when absent,
like the host). Everything else (httpx, parsing, filtering) is the real upstream code.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

PLUGIN_DIR = Path(__file__).resolve().parents[1]
FIXTURES = PLUGIN_DIR / "tests" / "fixtures"


class CoreSearch:
    def __init__(self, version: str, *, keys: dict | None = None, extra_providers: dict | None = None,
                 litellm_models: dict | None = None):
        if yaml is None:
            raise RuntimeError("PyYAML is required for the host characterization")
        self.version = version
        self.root = FIXTURES / f"a0-{version}"
        self.keys = dict(keys or {})
        providers = yaml.safe_load((self.root / "conf" / "model_providers.yaml").read_text(encoding="utf-8"))
        for model_type, table in (extra_providers or {}).items():
            providers.setdefault(model_type, {}).update(table)
        self.providers = providers
        self.litellm_models = litellm_models if litellm_models is not None else {}

    # -- stubs
    def _modules(self) -> dict:
        helpers = types.ModuleType("helpers")
        helpers.__path__ = []
        api = types.ModuleType("helpers.api")

        class ApiHandler:  # minimal stand-in
            pass

        api.ApiHandler, api.Request, api.Response = ApiHandler, object, object
        prov = types.ModuleType("helpers.providers")
        prov.get_provider_config = lambda model_type, provider: self.providers.get(model_type, {}).get(provider)
        models = types.ModuleType("models")
        models.get_api_key = lambda service: self.keys.get(service, "None")
        litellm = types.ModuleType("litellm")
        litellm.models_by_provider = self.litellm_models
        helpers.api, helpers.providers = api, prov
        return {"helpers": helpers, "helpers.api": api, "helpers.providers": prov, "models": models, "litellm": litellm}

    def module(self):
        path = self.root / "plugins" / "_model_config" / "api" / "model_search.py"
        spec = importlib.util.spec_from_file_location(f"_core_model_search_{self.version.replace('.', '_')}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def source(self) -> str:
        return (self.root / "plugins" / "_model_config" / "api" / "model_search.py").read_text(encoding="utf-8")

    def run(self, provider: str, api_base: str = "", query: str = "", model_type: str = "chat") -> dict:
        with mock.patch.dict(sys.modules, self._modules()):
            module = self.module()
            handler = module.ModelSearch()
            return asyncio.run(handler.process({"provider": provider, "api_base": api_base, "query": query, "model_type": model_type}, None))
