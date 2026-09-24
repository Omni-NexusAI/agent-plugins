import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" / "helpers" / "timeline.py"


class TimelineTests(unittest.TestCase):
    def setUp(self):
        helpers = types.ModuleType("helpers")
        self.config = {"main": {"enabled": True, "backend": "openrouter"}}
        helpers.plugins = types.SimpleNamespace(get_plugin_config=lambda *_: self.config)
        self.modules = patch.dict(sys.modules, {"helpers": helpers})
        self.modules.start()
        spec = importlib.util.spec_from_file_location("system_one_timeline_test", SOURCE)
        self.timeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.timeline)
        self.item = types.SimpleNamespace(updates=[])
        self.item.update = lambda **kw: self.item.updates.append(kw)
        self.logged = []
        self.agent = types.SimpleNamespace(
            loop_data=types.SimpleNamespace(iteration=0, params_temporary={}),
            last_user_message=types.SimpleNamespace(output_text=lambda: "Private request"),
            context=types.SimpleNamespace(log=types.SimpleNamespace(
                log=lambda **kw: self.logged.append(kw) or self.item)))

    def tearDown(self):
        self.modules.stop()

    def test_single_marked_step_updates_without_request_text(self):
        self.timeline.start_main_step(self.agent)
        self.timeline.start_main_step(self.agent)
        self.timeline.finish_main_step(self.agent, "Selected eligible action",
                                       confidence=0.8, action_name="memory_load")
        self.timeline.finish_main_step(self.agent, "Selected eligible action")
        self.assertEqual(len(self.logged), 1)
        self.assertEqual(len(self.item.updates), 1)
        self.assertEqual(self.logged[0]["type"], "info")
        self.assertTrue(self.logged[0]["id"].startswith("system1-main-"))
        self.assertEqual(self.item.updates[0]["kvps"]["Route"], "Selected eligible action")
        self.assertEqual(self.item.updates[0]["kvps"]["Action"], "memory_load")
        self.assertNotIn("Private request", str(self.logged) + str(self.item.updates))

    def test_disabled_mode_creates_no_step(self):
        self.config["main"]["enabled"] = False
        self.timeline.start_main_step(self.agent)
        self.assertFalse(self.logged)


if __name__ == "__main__":
    unittest.main()
