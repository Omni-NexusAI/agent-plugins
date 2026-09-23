import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "helpers" / "runtime.py"


class SpecialistTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "tool": {"enabled": True, "provider": "openrouter", "name": "test/model"},
            "coding": {"enabled": False, "provider": "", "name": ""},
            "policy": {"timeout_seconds": 3, "max_goal_chars": 1000},
        }
        helpers = types.ModuleType("helpers")
        helpers.plugins = types.SimpleNamespace(get_plugin_config=lambda _name, _agent: self.config)
        models = types.ModuleType("models")
        models.ModelType = types.SimpleNamespace(CHAT="chat")
        self.model = types.SimpleNamespace(unified_call=self._call)
        models.get_chat_model = lambda *args, **kwargs: self.model
        package_names = ("plugins", "plugins._model_config", "plugins._model_config.helpers")
        modules = {name: types.ModuleType(name) for name in package_names}
        builder = types.ModuleType("plugins._model_config.helpers.model_config")
        builder.build_model_config = lambda cfg, kind: types.SimpleNamespace(
            provider=cfg["provider"], name=cfg["name"], build_kwargs=lambda: {})
        modules[builder.__name__] = builder
        self.module_patch = patch.dict(sys.modules, {"helpers": helpers, "models": models, **modules})
        self.module_patch.start()
        spec = importlib.util.spec_from_file_location("auxiliary_roles_test_runtime", SOURCE)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)

    def tearDown(self):
        self.module_patch.stop()

    async def _call(self, **kwargs):
        return "Specialist proposal", ""

    def test_only_enabled_configured_roles_are_available(self):
        self.assertEqual(list(self.runtime.available_roles(object())), ["tool"])
        self.assertEqual(asyncio.run(self.runtime.delegate(object(), "tool", "Inspect the page")), "Specialist proposal")
        with self.assertRaises(ValueError):
            asyncio.run(self.runtime.delegate(object(), "coding", "Write code"))

    def test_disable_during_request_discards_result(self):
        async def disable(**kwargs):
            self.config["tool"]["enabled"] = False
            return "Late result", ""
        self.model.unified_call = disable
        with self.assertRaises(RuntimeError):
            asyncio.run(self.runtime.delegate(object(), "tool", "Inspect the page"))


if __name__ == "__main__":
    unittest.main()
