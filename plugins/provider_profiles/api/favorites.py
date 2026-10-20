"""POST /api/plugins/provider_profiles/favorites

Thin Agent Zero API handler; all behavior lives in helpers/favorites_store.py and
helpers/settings.py. Keep exactly ONE ApiHandler subclass in this file: the host
loader picks the alphabetically last subclass it finds.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
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


def _favorites_path() -> Path:
    override = os.environ.get("PROVIDER_PROFILES_DATA_DIR")
    if override:
        return Path(override) / "favorites.json"
    try:
        from helpers import files

        return Path(files.get_abs_path("usr", "plugins", PLUGIN_NAME, "favorites.json"))
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parent.parent / "favorites.json"


def _raw_config():
    try:
        from helpers import plugins

        return plugins.get_plugin_config(PLUGIN_NAME) or {}
    except Exception:  # noqa: BLE001
        return {}


class Favorites(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        store_module = _helper("favorites_store")
        settings = _helper("settings").merge_settings(_raw_config())
        store = store_module.FavoritesStore(_favorites_path())
        return await asyncio.to_thread(store_module.handle, input, store, settings)
