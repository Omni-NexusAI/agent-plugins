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

    def test_completed_spans_are_aggregate_only_and_allow_overlap(self):
        agent = types.SimpleNamespace()
        foreground = {}
        background = {}
        with patch.object(self.module.time, "monotonic", side_effect=[1, 2, 3, 4, 5, 6]):
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

    def test_unmatched_end_records_no_duration(self):
        agent = types.SimpleNamespace()
        self.module.finish(agent, "memory_recall")
        self.assertEqual(self.module.snapshot(agent)["memory_recall"],
                         {"calls": 0, "seconds": 0.0})


if __name__ == "__main__":
    unittest.main()
