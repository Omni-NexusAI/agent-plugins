import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero"
          / "api" / "metrics.py")


class MetricsApiTests(unittest.TestCase):
    def setUp(self):
        self.contexts = {}
        agent = types.ModuleType("agent")
        agent.AgentContext = types.SimpleNamespace(
            get=lambda context_id: self.contexts.get(context_id))
        helpers = types.ModuleType("helpers")
        api = types.ModuleType("helpers.api")
        api.ApiHandler = object
        api.Request = object
        class Response:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        api.Response = Response
        stages = types.ModuleType("usr.plugins.system_1.helpers.stage_metrics")
        stages.snapshot = lambda agent: {"tool_execution": {"calls": 1, "seconds": 0.5}}
        stages.spans_snapshot = lambda agent: {"spans": [
            {"stage": "tool_execution", "start": 1.0, "end": 1.5}], "dropped": 0}
        self.modules = patch.dict(sys.modules, {
            "agent": agent, "helpers": helpers, "helpers.api": api,
            stages.__name__: stages})
        self.modules.start()
        spec = importlib.util.spec_from_file_location("system_one_metrics_api_test", SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        self.modules.stop()

    def test_missing_context_returns_error(self):
        output = asyncio.run(self.module.Metrics().process({}, None))
        self.assertEqual(output.status, 400)

    def test_snapshot_contains_counts_only(self):
        active = types.SimpleNamespace(
            _system_1_utility_metrics={"calls": 3, "bypassed": 1,
                                       "decision_seconds": 0.25,
                                       "model_call_categories": {
                                           "memory_query": {"calls": 1, "seconds": 1.5},
                                           "private_prompt": {"calls": 1, "seconds": 99}},
                                       "memory_filter_gate": {"seen": 2,
                                                              "payload_oversize": 1,
                                                              "reason_candidate_length": 1,
                                                              "reason_confidence": 1,
                                                              "private_prompt": 100},
                                       "private_prompt": "do not return"})
        self.contexts["test-chat"] = types.SimpleNamespace(agent0=active)
        output = asyncio.run(self.module.Metrics().process(
            {"context": "test-chat"}, None))
        self.assertTrue(output["ok"])
        self.assertEqual(output["utility"]["calls"], 3)
        self.assertEqual(output["utility"]["bypassed"], 1)
        self.assertEqual(output["utility"]["decision_seconds"], 0.25)
        self.assertEqual(output["utility"]["model_call_categories"], {
            "memory_query": {"calls": 1, "seconds": 1.5}})
        self.assertEqual(output["utility"]["memory_filter_gate"]["seen"], 2)
        self.assertEqual(output["utility"]["memory_filter_gate"]["payload_oversize"], 1)
        self.assertEqual(output["utility"]["memory_filter_gate"]["reason_candidate_length"], 1)
        self.assertEqual(output["utility"]["memory_filter_gate"]["reason_confidence"], 1)
        self.assertEqual(output["stages"]["tool_execution"],
                         {"calls": 1, "seconds": 0.5})
        self.assertEqual(output["stage_spans"]["spans"][0]["end"], 1.5)
        self.assertNotIn("private_prompt", str(output))


if __name__ == "__main__":
    unittest.main()
