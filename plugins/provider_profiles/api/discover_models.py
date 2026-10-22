"""POST /api/plugins/provider_profiles/discover_models

Thin Agent Zero API handler; all behavior lives in helpers/endpoint_discovery.py and helpers/settings.py.
Keep exactly ONE ApiHandler subclass in this file: the host loader picks the alphabetically last subclass it finds.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

from helpers.api import ApiHandler, Request, Response

PLUGIN_NAME = "provider_profiles"
_MODULES: dict[str, object] = {}


def _helper(name: str):
    """Import a sibling helper module (files here execute standalone, without package context)."""
    module = _MODULES.get(name)
    if module is not None:
        return module
    try:
        module = importlib.import_module(f"usr.plugins.{PLUGIN_NAME}.helpers.{name}")
    except Exception:  # noqa: BLE001 - fall back to a path-based import
        path = Path(__file__).resolve().parent.parent / "helpers" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"_provider_profiles_{name}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    _MODULES[name] = module
    return module


def _raw_config():
    try:
        from helpers import plugins

        return plugins.get_plugin_config(PLUGIN_NAME) or {}
    except Exception:  # noqa: BLE001
        return {}


def _provider_config(model_type: str, provider: str):
    from helpers import providers

    return providers.get_provider_config(model_type, provider)


def _stored_key(provider: str):
    """The stored value for a provider (possibly several comma-separated keys).

    The host's get_api_key() advances a round-robin counter on every call when the value holds several keys;
    reading the raw value keeps that counter untouched (get_api_key_raw exists since v2.14, the same dotenv
    lookups serve v2.11).
    """
    try:
        import models

        reader = getattr(models, "get_api_key_raw", None)
        if reader is not None:
            return reader(provider)
    except Exception:  # noqa: BLE001
        pass
    try:
        from helpers import dotenv

        service = provider.upper()
        return (dotenv.get_dotenv_value(f"API_KEY_{service}") or dotenv.get_dotenv_value(f"{service}_API_KEY")
                or dotenv.get_dotenv_value(f"{service}_API_TOKEN"))
    except Exception:  # noqa: BLE001
        return None


class DiscoverModels(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        discovery = _helper("endpoint_discovery")
        settings = _helper("settings").merge_settings(_raw_config())
        return await discovery.handle(input, settings=settings, provider_config=_provider_config, stored_key=_stored_key)
