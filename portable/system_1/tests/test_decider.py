import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" /
          "helpers" / "runtime.py")


def load_runtime(config):
    helpers = types.ModuleType("helpers")
    helpers.plugins = types.SimpleNamespace(
        get_plugin_config=lambda _plugin, _agent: config)
    core = types.ModuleType("usr.plugins.system_1.helpers.system_1_core")
    core.DecisionClient = object
    core.DecisionError = RuntimeError
    decision = types.ModuleType(core.__name__ + ".decision")
    decision.selected_action = lambda *args, **kwargs: None
    timeline = types.ModuleType("usr.plugins.system_1.helpers.timeline")
    timeline.finish_main_step = lambda *args, **kwargs: None
    availability = types.ModuleType(
        "usr.plugins.system_1.helpers.tool_availability")
    availability.is_tool_available = lambda *args, **kwargs: True
    modules = patch.dict(sys.modules, {
        "helpers": helpers,
        core.__name__: core,
        decision.__name__: decision,
        timeline.__name__: timeline,
        availability.__name__: availability,
    })
    modules.start()
    spec = importlib.util.spec_from_file_location("system_one_decider_test", SOURCE)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    return runtime, modules


class DeciderConfigTests(unittest.TestCase):
    LEGACY_CONNECTION = {
        "backend": "jev",
        "provider": "jev",
        "model": "jev-latest",
        "endpoint": "https://decision.example/v1",
        "token_env": "SYSTEM_1_JEV_API_KEY",
    }

    def setUp(self):
        self.config = {}
        self.runtime, self.modules = load_runtime(self.config)

    def tearDown(self):
        self.modules.stop()

    def test_matching_legacy_connection_migrates_to_one_shared_decider(self):
        config = {
            "main": {"enabled": True, **self.LEGACY_CONNECTION},
            "utility": {"enabled": False, "fixed_routes": [], **self.LEGACY_CONNECTION},
            "embedding": {"enabled": True, **self.LEGACY_CONNECTION},
        }
        original = __import__("copy").deepcopy(config)

        migrated = self.runtime.migrate_decider_config(config)

        self.assertEqual(migrated["decider"], self.LEGACY_CONNECTION)
        self.assertEqual(migrated["main"], config["main"])
        self.assertEqual(migrated["utility"], config["utility"])
        self.assertEqual(config, original)

    def test_migration_is_idempotent_and_preserves_existing_decider(self):
        config = {
            "decider": {"backend": "chat", "provider": "openai", "model": "shared"},
            "main": {"enabled": True, **self.LEGACY_CONNECTION},
            "utility": {"enabled": True, "model": "different"},
        }

        once = self.runtime.migrate_decider_config(config)
        twice = self.runtime.migrate_decider_config(once)

        self.assertEqual(once, twice)
        self.assertEqual(once["decider"], config["decider"])
        self.assertIsNot(once, config)
        self.assertIsNot(once["decider"], config["decider"])

    def test_conflicting_legacy_connection_does_not_guess_a_decider(self):
        config = {
            "main": {"enabled": True, **self.LEGACY_CONNECTION},
            "utility": {"enabled": True, **{**self.LEGACY_CONNECTION, "model": "other"}},
            "embedding": {"enabled": False, **self.LEGACY_CONNECTION},
        }

        migrated = self.runtime.migrate_decider_config(config)

        self.assertNotIn("decider", migrated)
        self.assertEqual(migrated["main"], config["main"])
        self.assertEqual(migrated["utility"], config["utility"])
        self.assertEqual(migrated["embedding"], config["embedding"])

    def test_enabled_section_uses_decider_connection_and_keeps_role_settings(self):
        self.config.update({
            "decider": {
                "backend": "chat",
                "provider": "openai",
                "model": "shared-decider",
                "endpoint": "https://shared.example/v1",
                "token_env": "SHARED_DECIDER_KEY",
                "context_window": 32768,
            },
            "main": {
                "enabled": True,
                "backend": "jev",
                "model": "legacy-main",
                "action_label": "main routing",
            },
            "utility": {"enabled": False, "fixed_routes": [{"message": "x"}]},
            "policy": {"max_state_chars": 4000},
        })

        settings = self.runtime.config_for(types.SimpleNamespace(), "main")

        self.assertIsNotNone(settings)
        section, policy = settings
        self.assertTrue(section["enabled"])
        self.assertEqual(section["action_label"], "main routing")
        self.assertEqual(section["backend"], "chat")
        self.assertEqual(section["provider"], "openai")
        self.assertEqual(section["model"], "shared-decider")
        self.assertEqual(section["endpoint"], "https://shared.example/v1")
        self.assertEqual(section["token_env"], "SHARED_DECIDER_KEY")
        self.assertEqual(section["context_window"], 32768)
        self.assertEqual(policy, {"max_state_chars": 4000})

    def test_disabled_section_remains_ineligible_even_with_decider(self):
        self.config.update({
            "decider": {"backend": "jev", "model": "shared"},
            "main": {"enabled": False},
            "utility": {"enabled": False},
            "embedding": {"enabled": False},
        })

        for section in ("main", "utility", "embedding"):
            self.assertIsNone(self.runtime.config_for(types.SimpleNamespace(), section))

    def test_missing_decider_retains_legacy_enabled_section_behavior(self):
        self.config.update({
            "main": {"enabled": True, **self.LEGACY_CONNECTION},
            "policy": {"timeout_seconds": 2.0},
        })

        section, policy = self.runtime.config_for(types.SimpleNamespace(), "main")

        self.assertEqual(section, self.config["main"])
        self.assertEqual(policy, self.config["policy"])

    def test_context_window_rejects_incomplete_utf8_state(self):
        choices = {"main": "Use normal model", "tool": "Use fixed host tool"}
        state = "é" * 2000
        with self.assertRaisesRegex(RuntimeError, "state exceeds"):
            self.runtime.bound_decision_state(state, choices, 1024)
        self.assertEqual(
            self.runtime.bound_decision_state("Complete state", choices, 1024),
            "Complete state",
        )

    def test_context_window_never_discards_main_correction_or_utility_message(self):
        for state in (
            "Original request: " + "x" * 2000 + "\nMain correction: Choose verified source",
            "System instruction: classify\nUser message: " + "x" * 2000,
        ):
            with self.subTest(state=state[:20]):
                with self.assertRaisesRegex(RuntimeError, "state exceeds"):
                    self.runtime.bound_decision_state(state, {"main": "Fallback"}, 1024)

    def test_context_window_rejects_oversized_choices(self):
        with self.assertRaisesRegex(RuntimeError, "choices exceed"):
            self.runtime.bound_decision_state("request", {"route": "x" * 2000}, 1024)

    def test_shared_connection_does_not_inherit_legacy_endpoint_or_key(self):
        self.config.update({
            "decider": {"backend": "openrouter", "provider": "openrouter",
                        "model": "typesafe/jev-latest"},
            "main": {"enabled": True, "endpoint": "https://old.example",
                     "token_env": "OLD_KEY", "model": "old"},
        })
        section, _ = self.runtime.config_for(types.SimpleNamespace(), "main")
        self.assertNotIn("endpoint", section)
        self.assertNotIn("token_env", section)
        self.assertEqual(section["model"], "typesafe/jev-latest")


if __name__ == "__main__":
    unittest.main()
