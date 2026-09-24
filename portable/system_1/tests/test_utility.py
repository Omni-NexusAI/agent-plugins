import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


BASE = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero"
SOURCE = BASE / "helpers" / "utility.py"
HOOK = BASE / "extensions" / "python" / "util_model_call_before" / "_20_system_1.py"


class OriginalModel:
    def __init__(self):
        self.calls = []

    async def unified_call(self, **kwargs):
        self.calls.append(kwargs)
        return "generated", "reasoning"


class UtilityTests(unittest.TestCase):
    def setUp(self):
        self.route = {"system": "Classify exactly", "message": "Item A",
                      "responses": {"yes": "YES", "no": "NO"}}
        self.config = {"utility": {"enabled": True, "backend": "jev",
                                   "fixed_routes": [self.route]},
                       "policy": {"min_choice_probability": 0.85}}
        self.decision = types.SimpleNamespace(choice="yes", confidence=0.96)
        self.choices = []
        self.backend_calls = 0
        self.agent = types.SimpleNamespace()
        self.original = OriginalModel()
        self.call_data = {"system": "Classify exactly", "message": "Item A",
                          "model": self.original}

        async def choose(state, choices):
            self.backend_calls += 1
            self.choices.append((state, choices))
            return self.decision

        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.config_for = lambda agent, section: (
            (self.config[section], self.config["policy"])
            if self.config[section]["enabled"] else None)
        runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=choose)
        runtime.memory_decision = self.memory_decision
        runtime.utility_decision = self.utility_decision
        self.guidance_calls = []
        self.modules = patch.dict(sys.modules, {
            "usr.plugins.system_1.helpers.runtime": runtime,
            "usr.plugins.system_1.helpers.utility": types.ModuleType(
                "usr.plugins.system_1.helpers.utility")})
        self.modules.start()
        spec = importlib.util.spec_from_file_location("utility_under_test", SOURCE)
        self.utility = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.utility)

    def tearDown(self):
        self.modules.stop()

    async def memory_decision(self, *args):
        self.guidance_calls.append("memory")
        return "normal"

    async def utility_decision(self, *args):
        self.guidance_calls.append("utility")

    def run_call(self, callback=None, **overrides):
        return asyncio.run(self.call_data["model"].unified_call(
            system_message=overrides.get("system_message", self.call_data["system"]),
            user_message=overrides.get("user_message", self.call_data["message"]),
            response_callback=callback, rate_limiter_callback=None))

    def test_exact_high_confidence_response_bypasses_model_and_preserves_callback(self):
        self.assertTrue(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, self.call_data)))
        chunks = []

        async def callback(chunk, total):
            chunks.append((chunk, total))

        self.assertEqual(self.run_call(callback), ("YES", ""))
        self.assertEqual(chunks, [("YES", "YES")])
        self.assertEqual(self.original.calls, [])
        self.assertEqual(self.backend_calls, 1)
        self.assertIn("ordinary", self.choices[0][1])
        self.assertIn("System instruction: Classify exactly", self.choices[0][0])
        self.assertIn("User message: Item A", self.choices[0][0])
        self.assertIn("YES", self.choices[0][1]["yes"])
        self.assertEqual(self.utility.metrics(self.agent)["bypassed"], 1)
        self.assertGreaterEqual(self.utility.metrics(self.agent)["decision_seconds"], 0)

    def test_unknown_call_does_not_consult_backend(self):
        self.call_data["message"] = "Item B"
        self.assertFalse(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, self.call_data)))
        self.assertIs(self.call_data["model"], self.original)
        self.assertEqual(self.backend_calls, 0)

    def test_existing_agent_metrics_gain_call_counter(self):
        self.agent._system_1_utility_metrics = {"decisions": 2, "bypassed": 1,
                                                "fallbacks": 1,
                                                "decision_seconds": 0.2,
                                                "fallback_model_seconds": 0.0}
        self.assertEqual(self.utility.metrics(self.agent)["calls"], 0)

    def test_low_confidence_and_ordinary_fall_back(self):
        for decision in (types.SimpleNamespace(choice="yes", confidence=0.3),
                         types.SimpleNamespace(choice="ordinary", confidence=1.0)):
            self.decision = decision
            self.assertFalse(asyncio.run(self.utility.install_fixed_utility_response(
                self.agent, self.call_data)))
        self.assertIs(self.call_data["model"], self.original)
        self.assertEqual(self.utility.metrics(self.agent)["fallbacks"], 2)

    def test_backend_error_falls_back(self):
        def fail(section, policy):
            raise RuntimeError("unavailable")

        with patch.object(sys.modules["usr.plugins.system_1.helpers.runtime"],
                          "client_for", fail):
            # utility.py imported the function directly, so patch its binding.
            self.utility.client_for = fail
            self.assertFalse(asyncio.run(self.utility.install_fixed_utility_response(
                self.agent, self.call_data)))
        self.assertIs(self.call_data["model"], self.original)

    def test_revocation_and_changed_request_use_original_model(self):
        self.assertTrue(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, self.call_data)))
        self.config["utility"]["fixed_routes"][0]["responses"]["yes"] = "CHANGED"
        self.assertEqual(self.run_call(), ("generated", "reasoning"))
        self.assertEqual(len(self.original.calls), 1)
        self.assertEqual(self.utility.metrics(self.agent)["fallbacks"], 1)

        self.config["utility"]["fixed_routes"][0]["responses"]["yes"] = "YES"
        self.call_data["model"] = self.original
        self.assertTrue(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, self.call_data)))
        self.assertEqual(self.run_call(user_message="Item B"), ("generated", "reasoning"))
        self.assertEqual(len(self.original.calls), 2)

        self.call_data["model"] = self.original
        self.assertTrue(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, self.call_data)))
        self.config["policy"]["min_choice_probability"] = 0.99
        self.assertEqual(self.run_call(), ("generated", "reasoning"))
        self.assertEqual(len(self.original.calls), 3)

    def test_chat_backend_and_long_message_are_ineligible(self):
        self.config["utility"]["backend"] = "chat"
        self.assertFalse(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, self.call_data)))
        self.config["utility"]["backend"] = "jev"
        self.config["policy"]["max_state_chars"] = 3
        self.assertFalse(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, self.call_data)))
        self.assertEqual(self.backend_calls, 0)

    def test_hook_returns_after_installing_bypass(self):
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {"__init__": lambda obj, agent: setattr(obj, "agent", agent)})
        sys.modules["usr.plugins.system_1.helpers.utility"].install_fixed_utility_response = (
            self.utility.install_fixed_utility_response)
        sys.modules["usr.plugins.system_1.helpers.utility"].metrics = self.utility.metrics
        with patch.dict(sys.modules, {"helpers.extension": extension}):
            spec = importlib.util.spec_from_file_location("utility_hook_under_test", HOOK)
            hook = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hook)
            asyncio.run(hook.SystemOneUtility(self.agent).execute(self.call_data))
        self.assertEqual(self.guidance_calls, [])
        self.assertEqual(self.utility.metrics(self.agent)["calls"], 1)
        self.assertEqual(self.run_call(), ("YES", ""))

    def test_decided_fallback_skips_second_decision(self):
        self.decision = types.SimpleNamespace(choice="ordinary", confidence=1.0)
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {
            "__init__": lambda obj, agent: setattr(obj, "agent", agent)})
        sys.modules["usr.plugins.system_1.helpers.utility"].install_fixed_utility_response = (
            self.utility.install_fixed_utility_response)
        sys.modules["usr.plugins.system_1.helpers.utility"].metrics = self.utility.metrics
        with patch.dict(sys.modules, {"helpers.extension": extension}):
            spec = importlib.util.spec_from_file_location("utility_hook_fallback_test", HOOK)
            hook = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hook)
            asyncio.run(hook.SystemOneUtility(self.agent).execute(self.call_data))
        self.assertEqual(self.backend_calls, 1)
        self.assertEqual(self.guidance_calls, [])
        self.assertIs(self.call_data["model"], self.original)


if __name__ == "__main__":
    unittest.main()
