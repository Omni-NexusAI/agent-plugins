import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch


SOURCE = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero"
          / "helpers" / "stage_metrics.py")


class StageMetricsTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("system_one_stage_metrics", SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_completed_spans_retain_bounded_relative_times_and_allow_overlap(self):
        agent = types.SimpleNamespace()
        foreground = {}
        background = {}
        with patch.object(self.module.time, "monotonic", side_effect=[0, 1, 2, 3, 4, 5, 6]):
            self.module.begin(agent, "main_foreground", foreground)
            self.module.begin(agent, "main_background", background)
            self.module.finish(agent, "main_foreground", foreground)
            self.module.finish(agent, "main_background", background)
            self.module.begin(agent, "tool_execution")
            self.module.finish(agent, "tool_execution")
        output = self.module.snapshot(agent)
        self.assertEqual(output["main_foreground"], {"calls": 1, "seconds": 2})
        self.assertEqual(output["main_background"], {"calls": 1, "seconds": 2})
        self.assertEqual(output["tool_execution"], {"calls": 1, "seconds": 1})
        self.assertNotIn("active", str(output))
        spans = self.module.spans_snapshot(agent)
        self.assertEqual(spans["dropped"], 0)
        self.assertEqual(spans["spans"], [
            {"stage": "main_foreground", "start": 1, "end": 3},
            {"stage": "main_background", "start": 2, "end": 4},
            {"stage": "tool_execution", "start": 5, "end": 6},
        ])

    def test_unmatched_end_records_no_duration(self):
        agent = types.SimpleNamespace()
        self.module.finish(agent, "memory_recall")
        self.assertEqual(self.module.snapshot(agent)["memory_recall"],
                         {"calls": 0, "seconds": 0.0})

    def test_span_history_is_bounded_without_losing_totals(self):
        agent = types.SimpleNamespace()
        for _ in range(257):
            self.module.begin(agent, "tool_execution")
            self.module.finish(agent, "tool_execution")
        result = self.module.spans_snapshot(agent)
        self.assertEqual(len(result["spans"]), 256)
        self.assertEqual(result["dropped"], 1)
        self.assertEqual(self.module.snapshot(agent)["tool_execution"]["calls"], 257)

    def test_hot_loaded_aggregate_record_migrates_without_losing_totals(self):
        agent = types.SimpleNamespace(_system_1_stage_metrics={
            "active": {}, "totals": {"tool_execution": {"calls": 2, "seconds": 3.0}}})
        self.module.begin(agent, "tool_execution")
        self.module.finish(agent, "tool_execution")
        self.assertEqual(self.module.snapshot(agent)["tool_execution"]["calls"], 3)
        self.assertEqual(len(self.module.spans_snapshot(agent)["spans"]), 1)


if __name__ == "__main__":
    unittest.main()
