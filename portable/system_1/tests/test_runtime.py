import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" / "helpers" / "runtime.py"


class Agent:
    loop_data = types.SimpleNamespace(iteration=0)
    last_user_message = types.SimpleNamespace(output_text=lambda: "Inspect this page")


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = {"main": {"enabled": True, "backend": "jev", "model": "jev-latest"},
                       "policy": {"action_precedence": "tool_first", "actions": {}}}
        helpers = types.ModuleType("helpers")
        helpers.plugins = types.SimpleNamespace(get_plugin_config=lambda _name, _agent: self.config)
        core = types.ModuleType("usr.plugins.system_1.helpers.system_1_core")
        core.DecisionClient = object
        core.DecisionError = RuntimeError
        decision = types.ModuleType(core.__name__ + ".decision")
        decision.selected_action = lambda *args, **kwargs: None
        timeline = types.ModuleType("usr.plugins.system_1.helpers.timeline")
        self.timeline_events = []
        timeline.finish_main_step = lambda *args, **kwargs: self.timeline_events.append((args, kwargs))
        auxiliary = types.ModuleType("usr.plugins.auxiliary_model_roles.helpers.runtime")
        auxiliary.available_roles = lambda agent: {"tool": {"enabled": True}}
        self.modules = patch.dict(sys.modules, {"helpers": helpers, core.__name__: core,
                                                decision.__name__: decision, timeline.__name__: timeline,
                                                auxiliary.__name__: auxiliary})
        self.modules.start()
        spec = importlib.util.spec_from_file_location("system_one_runtime_test", SOURCE)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)

    def tearDown(self):
        self.modules.stop()

    def test_tool_first_uses_normal_host_delegation_tool(self):
        result = asyncio.run(self.runtime.main_decision(Agent()))
        self.assertEqual(json.loads(result), {"tool_name": "auxiliary_delegate",
                                               "tool_args": {"role": "tool", "goal": "Inspect this page"}})
        self.assertEqual(self.timeline_events[-1][0][1], "Delegated to Tool")

    def test_disabled_main_escalates(self):
        self.config["main"]["enabled"] = False
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))

    def test_later_iterations_leave_tool_results_to_host(self):
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=1)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))

    def test_disabling_during_backend_call_prevents_late_dispatch(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {"memory": {"tool_name": "memory_load", "tool_args": {"query": "test"}}}
        async def decide(state, choices):
            self.config["main"]["enabled"] = False
            return types.SimpleNamespace(choice="memory", confidence=0.99)
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))
        self.assertEqual(self.timeline_events[-1][1]["detail"], "Mode disabled during decision")

    def test_eligible_action_names_host_tool_in_timeline(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "recall": {"tool_name": "memory_load", "tool_args": {"query": "current project"}}}
        async def decide(state, choices):
            return types.SimpleNamespace(choice="recall", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions["recall"]
        result = asyncio.run(self.runtime.main_decision(Agent()))
        self.assertEqual(json.loads(result)["tool_name"], "memory_load")
        self.assertEqual(self.timeline_events[-1][1]["action_name"], "memory_load")


if __name__ == "__main__":
    unittest.main()
