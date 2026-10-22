"""POST /api/plugins/provider_profiles/discover_models: settings, handler file shape and host integration (stubbed host)."""
from __future__ import annotations

import ast
import asyncio
import json
import sys
import types
import unittest
from unittest import mock

from .fake_endpoints import FakeEndpoint
from .loader import PLUGIN_DIR, load_helper, load_module

settings_mod = load_helper("settings")


class DiscoverySettings(unittest.TestCase):
    def test_defaults(self):
        self.assertIs(settings_mod.DEFAULTS["discovery_enabled"], True)
        self.assertIs(settings_mod.DEFAULTS["discovery_fill_on_select"], False)

    def test_booleans_override_and_nothing_else_does(self):
        merged = settings_mod.merge_settings({"discovery_enabled": False, "discovery_fill_on_select": True})
        self.assertEqual((merged["discovery_enabled"], merged["discovery_fill_on_select"]), (False, True))
        for junk in ("false", 0, 1, None, [], "yes"):
            merged = settings_mod.merge_settings({"discovery_enabled": junk, "discovery_fill_on_select": junk})
            self.assertEqual((merged["discovery_enabled"], merged["discovery_fill_on_select"]), (True, False), junk)

    def test_flags_off_equals_the_pr1_defaults_for_every_other_key(self):
        off = settings_mod.merge_settings({"discovery_enabled": False})
        on = settings_mod.merge_settings({})
        self.assertEqual({k: v for k, v in off.items() if k != "discovery_enabled"}, {k: v for k, v in on.items() if k != "discovery_enabled"})


class HandlerFile(unittest.TestCase):
    SRC = PLUGIN_DIR / "api" / "discover_models.py"

    def test_exactly_one_api_handler_class(self):
        tree = ast.parse(self.SRC.read_text(encoding="utf-8"))
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        self.assertEqual([c.name for c in classes], ["DiscoverModels"])
        self.assertEqual([getattr(b, "id", None) for b in classes[0].bases], ["ApiHandler"])

    def test_the_handler_does_not_loosen_the_default_request_protections(self):
        source = self.SRC.read_text(encoding="utf-8")
        for loosened in ("requires_csrf", "requires_auth", "requires_loopback", "requires_api_key", "get_methods", "get_csrf"):
            self.assertNotIn(loosened, source, f"the handler must keep the host defaults ({loosened})")


class Host:
    """Stub of the Agent Zero modules the handler imports; records key reads."""

    def __init__(self, *, config=None, providers=None, env=None, key_reader=True):
        self.config = config or {}
        self.providers = providers or {}
        self.env = env or {}
        self.calls = []
        helpers = types.ModuleType("helpers")
        api = types.ModuleType("helpers.api")

        class ApiHandler:  # minimal stand-in for Agent Zero's helpers.api.ApiHandler
            pass

        api.ApiHandler, api.Request, api.Response = ApiHandler, object, object
        plugins = types.ModuleType("helpers.plugins")
        plugins.get_plugin_config = lambda name: self.config
        provider_mod = types.ModuleType("helpers.providers")
        provider_mod.get_provider_config = lambda model_type, provider: self.providers.get((model_type, provider))
        dotenv = types.ModuleType("helpers.dotenv")

        def get_dotenv_value(name, default=None):
            self.calls.append(("dotenv", name))
            return self.env.get(name, default)

        dotenv.get_dotenv_value = get_dotenv_value
        models = types.ModuleType("models")

        def get_api_key(service):
            self.calls.append(("get_api_key", service))
            raise AssertionError("get_api_key advances the host's round-robin counter and must never be used")

        models.get_api_key = get_api_key
        if key_reader:
            models.get_api_key_raw = lambda service: self.calls.append(("raw", service)) or self.env.get(f"API_KEY_{service.upper()}", "None")
        helpers.api, helpers.plugins, helpers.providers, helpers.dotenv = api, plugins, provider_mod, dotenv
        self.modules = {"helpers": helpers, "helpers.api": api, "helpers.plugins": plugins, "helpers.providers": provider_mod,
                        "helpers.dotenv": dotenv, "models": models}

    def patch(self):
        return mock.patch.dict(sys.modules, self.modules)


def process(host, payload):
    with host.patch():
        module = load_module("api/discover_models.py")
        return asyncio.run(module.DiscoverModels().process(payload, None))


class RoundTrip(unittest.TestCase):
    def test_discovers_through_the_host_provider_configuration(self):
        with FakeEndpoint("llamacpp_router") as ep:
            host = Host(providers={("chat", "llama_cpp"): {"kwargs": {"api_base": ep.url + "/v1"}, "models_list": {"endpoint_url": "/v1/models"}}})
            result = process(host, {"provider": "llama_cpp", "model_type": "chat"})
        self.assertIsNone(result["error"])
        self.assertEqual(result["endpoint"]["kind"], "llama_cpp_router")
        self.assertEqual(len(result["entries"]), 7)

    def test_the_stored_key_is_read_raw_on_v2_14_and_never_through_the_round_robin(self):
        with FakeEndpoint("lmstudio", token="k1") as ep:
            host = Host(env={"API_KEY_LM_STUDIO": "k1, k2"})
            result = process(host, {"provider": "lm_studio", "api_base": ep.url + "/v1"})
            self.assertEqual(ep.requests[0]["headers"]["authorization"], "Bearer k1")
        self.assertIsNone(result["error"])
        self.assertIn(("raw", "lm_studio"), host.calls)
        self.assertNotIn("get_api_key", [call[0] for call in host.calls])

    def test_v2_11_falls_back_to_the_same_dotenv_lookups_in_the_same_order(self):
        with FakeEndpoint("lmstudio", token="tok") as ep:
            host = Host(env={"LM_STUDIO_API_TOKEN": "tok"}, key_reader=False)
            result = process(host, {"provider": "lm_studio", "api_base": ep.url + "/v1"})
        self.assertIsNone(result["error"])
        self.assertEqual([c[1] for c in host.calls if c[0] == "dotenv"], ["API_KEY_LM_STUDIO", "LM_STUDIO_API_KEY", "LM_STUDIO_API_TOKEN"])
        self.assertNotIn("get_api_key", [call[0] for call in host.calls])

    def test_a_missing_key_means_no_authorization_header(self):
        with FakeEndpoint("lmstudio") as ep:
            host = Host(key_reader=False)
            result = process(host, {"provider": "lm_studio", "api_base": ep.url + "/v1"})
            self.assertNotIn("authorization", ep.requests[0]["headers"])
        self.assertIsNone(result["error"])

    def test_the_plugin_setting_turns_discovery_off(self):
        with FakeEndpoint("lmstudio") as ep:
            host = Host(config={"discovery_enabled": False})
            result = process(host, {"provider": "lm_studio", "api_base": ep.url + "/v1"})
            self.assertEqual(ep.requests, [], "nothing was contacted")
        self.assertEqual((result["ok"], result["skipped"], result["entries"]), (True, "disabled", []))

    def test_config_json_without_the_new_keys_keeps_discovery_on(self):
        with FakeEndpoint("lmstudio") as ep:
            host = Host(config={"favorites_ui": "on"})  # an old config.json replaces the defaults wholesale
            result = process(host, {"provider": "lm_studio", "api_base": ep.url + "/v1"})
        self.assertIsNone(result["skipped"])
        self.assertEqual(result["endpoint"]["kind"], "lm_studio")

    def test_the_response_is_plain_json(self):
        with FakeEndpoint("strata_router") as ep:
            result = process(Host(), {"provider": "strata_router", "api_base": ep.url + "/v1"})
        json.dumps(result)
        self.assertEqual(result["endpoint"]["kind"], "strata_router")

    def test_non_object_input_is_rejected_cleanly(self):
        result = process(Host(), ["not", "an", "object"])
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
