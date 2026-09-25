import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" /
          "tools" / "system1_delegate.py")


class DelegateToolTests(unittest.TestCase):
    def _load(self, accepted):
        helpers_tool = types.ModuleType("helpers.tool")

        class Response:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class Tool:
            args = {}

        helpers_tool.Response = Response
        helpers_tool.Tool = Tool
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        calls = []
        runtime.record_main_delegation = lambda agent, ids: calls.append((agent, ids)) or accepted
        modules = patch.dict(sys.modules, {helpers_tool.__name__: helpers_tool,
                                           runtime.__name__: runtime})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location("system_one_delegate_tool_test", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tool = module.System1Delegate()
        tool.agent = object()
        return tool, calls

    def test_main_tool_hands_only_valid_ids_to_host_runtime(self):
        tool, calls = self._load(True)

        response = __import__("asyncio").run(tool.execute(action_ids=["first", "second"]))

        self.assertEqual(calls, [(tool.agent, ["first", "second"])])
        self.assertFalse(response.break_loop)
        self.assertIn("choose", response.message)

    def test_invalid_ids_never_call_runtime_or_end_main_loop(self):
        tool, calls = self._load(True)

        response = __import__("asyncio").run(tool.execute(action_ids=["", 4]))

        self.assertEqual(calls, [])
        self.assertFalse(response.break_loop)
        self.assertIn("eligible action IDs", response.message)

    def test_rejected_delegation_leaves_main_responsible_for_the_task(self):
        tool, calls = self._load(False)

        response = __import__("asyncio").run(tool.execute(action_ids=["stale"]))

        self.assertEqual(calls, [(tool.agent, ["stale"])])
        self.assertFalse(response.break_loop)
        self.assertIn("Main should continue", response.message)


if __name__ == "__main__":
    unittest.main()
