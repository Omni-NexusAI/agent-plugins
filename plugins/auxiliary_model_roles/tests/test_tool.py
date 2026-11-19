import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tools" / "auxiliary_delegate.py"


class FakeHistory:
    text = "before"
    def output_text(self):
        return self.text


class FakeAgent:
    def __init__(self):
        self.history = FakeHistory()
        self.loop_data = types.SimpleNamespace(current_tool="outer")
        self.calls = []

    async def validate_tool_request(self, request):
        self.calls.append("validate")

    async def _execute_tool_request(self, **kwargs):
        self.calls.append(kwargs["tool_name"])
        self.history.text += "\nread-only host result"
        return None


class ToolTests(unittest.TestCase):
    def setUp(self):
        helper_tool = types.ModuleType("helpers.tool")
        helper_tool.Tool = object
        helper_tool.Response = lambda message, break_loop: types.SimpleNamespace(message=message, break_loop=break_loop)
        runtime = types.ModuleType("usr.plugins.auxiliary_model_roles.helpers.runtime")
        runtime.delegate = self.delegate
        self.modules = patch.dict(sys.modules, {"helpers.tool": helper_tool, runtime.__name__: runtime})
        self.modules.start()
        spec = importlib.util.spec_from_file_location("auxiliary_delegate_test", SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        self.modules.stop()

    async def delegate(self, agent, role, goal):
        return json.dumps({"tool_name": "memory_load", "tool_args": {"query": "test"}})

    def test_one_action_uses_native_executor_and_restores_outer_tool(self):
        agent = FakeAgent()
        tool = self.module.AuxiliaryDelegate()
        tool.agent = agent
        response = asyncio.run(tool.execute(role="tool", goal="Retrieve context"))
        self.assertEqual(agent.calls, ["validate", "memory_load"])
        self.assertEqual(agent.loop_data.current_tool, "outer")
        self.assertIn("read-only host result", response.message)
        self.assertFalse(response.break_loop)

    def test_recursive_delegation_is_returned_to_main(self):
        async def recursive(agent, role, goal):
            return json.dumps({"tool_name": "auxiliary_delegate", "tool_args": {"role": "tool", "goal": "again"}})
        self.module.delegate = recursive
        agent = FakeAgent()
        tool = self.module.AuxiliaryDelegate()
        tool.agent = agent
        response = asyncio.run(tool.execute(role="tool", goal="Do something"))
        self.assertEqual(agent.calls, [])
        self.assertIn("result for Main", response.message)


if __name__ == "__main__":
    unittest.main()
