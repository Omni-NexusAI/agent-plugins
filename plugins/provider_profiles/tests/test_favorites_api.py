from __future__ import annotations

import ast
import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from .loader import PLUGIN_DIR, load_helper, load_module

settings_mod = load_helper("settings")


class Settings(unittest.TestCase):
    def test_defaults_when_missing_or_invalid(self):
        for raw in (None, {}, [], "x", {"favorites_ui": "maybe", "favorites_shown": 0, "normal_results_mode": "wide"}):
            with self.subTest(raw=raw):
                merged = settings_mod.merge_settings(raw)
                self.assertEqual(merged, settings_mod.DEFAULTS)

    def test_valid_overrides(self):
        merged = settings_mod.merge_settings({
            "favorites_ui": "off", "favorites_shown": "7", "normal_results_mode": "core",
            "local_provider_defaults": {"lm_studio": " http://x:1/v1 ", "ollama": "", "other": "ignored"},
            "clear_stale_model_on_new_provider": False, "history_storage_key": "obsolete",
        })
        self.assertEqual(merged["favorites_ui"], "off")
        self.assertEqual(merged["favorites_shown"], 7)
        self.assertEqual(merged["normal_results_mode"], "core")
        self.assertEqual(merged["local_provider_defaults"]["lm_studio"], "http://x:1/v1")
        self.assertEqual(merged["local_provider_defaults"]["ollama"], settings_mod.BUILTIN_LOCAL_DEFAULTS["ollama"])
        self.assertNotIn("other", merged["local_provider_defaults"])
        self.assertFalse(merged["clear_stale_model_on_new_provider"])
        self.assertNotIn("history_storage_key", merged)

    def test_defaults_are_not_shared_between_calls(self):
        a = settings_mod.merge_settings({})
        a["local_provider_defaults"]["lm_studio"] = "mutated"
        self.assertNotEqual(settings_mod.merge_settings({})["local_provider_defaults"]["lm_studio"], "mutated")

    def test_bool_is_not_a_number(self):
        self.assertEqual(settings_mod.merge_settings({"favorites_shown": True})["favorites_shown"], 5)


class HandlerFile(unittest.TestCase):
    SRC = PLUGIN_DIR / "api" / "favorites.py"

    def test_exactly_one_api_handler_class(self):
        tree = ast.parse(self.SRC.read_text(encoding="utf-8"))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        self.assertEqual([c.name for c in classes], ["Favorites"])
        self.assertEqual([getattr(b, "id", None) for b in classes[0].bases], ["ApiHandler"])

    def _stub_host(self):
        helpers = types.ModuleType("helpers")
        api = types.ModuleType("helpers.api")

        class ApiHandler:  # minimal stand-in for Agent Zero's helpers.api.ApiHandler
            pass

        api.ApiHandler, api.Request, api.Response = ApiHandler, object, object
        helpers.api = api
        return mock.patch.dict(sys.modules, {"helpers": helpers, "helpers.api": api})

    def test_process_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, self._stub_host(), mock.patch.dict(os.environ, {"PROVIDER_PROFILES_DATA_DIR": tmp}):
            module = load_module("api/favorites.py")
            handler = module.Favorites()
            boot = asyncio.run(handler.process({"action": "bootstrap"}, None))
            self.assertTrue(boot["ok"])
            self.assertEqual(boot["settings"]["favorites_shown"], 5)
            res = asyncio.run(handler.process({"action": "set", "model_type": "chat", "provider": "other", "api_base": "http://h:1/v1", "name": "alias-a", "on": True}, None))
            self.assertTrue(res["ok"] and res["starred"])
            self.assertTrue((Path(tmp) / "favorites.json").exists())
            again = asyncio.run(handler.process({"action": "list"}, None))
            self.assertEqual(again["types"]["chat"][0]["name"], "alias-a")
            bad = asyncio.run(handler.process({"action": "set", "model_type": "chat", "provider": "p", "api_base": "http://u:p@h", "name": "m", "on": True}, None))
            self.assertEqual(bad["error"], "api_base_credentials")


if __name__ == "__main__":
    unittest.main()
