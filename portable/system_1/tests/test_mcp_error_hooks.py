import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" / "extensions" / "python"
BEFORE = ROOT / "tool_execute_before" / "_20_system_1_mcp_error.py"
AFTER = ROOT / "tool_execute_after" / "_10_system_1_mcp_error.py"


class MCPErrorHookTests(unittest.TestCase):
    def _load(self, source, name):
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {})
        modules = patch.dict(sys.modules, {extension.__name__: extension})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_before_hook_captures_only_the_matching_native_mcp_log_boundary(self):
        module = self._load(BEFORE, "system_one_mcp_error_start_test")
        tool = types.SimpleNamespace(name="github_mcp_server.get_issue", _system1_mcp_log_start=None)
        agent = types.SimpleNamespace(loop_data=types.SimpleNamespace(current_tool=tool),
                                      context=types.SimpleNamespace(log=types.SimpleNamespace(logs=[1, 2])))
        hook = module.SystemOneMCPErrorStart()
        hook.agent = agent

        hook.execute(tool_name="github_mcp_server.get_issue")
        self.assertEqual(tool._system1_mcp_log_start, 2)
        hook.execute(tool_name="memory_load")
        self.assertEqual(tool._system1_mcp_log_start, 2)

    def test_after_hook_marks_native_iserror_and_prefixes_parallel_child_result(self):
        module = self._load(AFTER, "system_one_mcp_error_end_test")
        tool_name = "github_mcp_server.get_issue"
        tool = types.SimpleNamespace(name=tool_name, _system1_mcp_log_start=1)
        logs = [types.SimpleNamespace(type="info", content="older"),
                types.SimpleNamespace(type="warning", content=tool_name + ": isError true")]
        context = types.SimpleNamespace(log=types.SimpleNamespace(logs=logs),
                                        get_data=lambda key: "parallel-child" if key == "_parallel_job_id" else None)
        agent = types.SimpleNamespace(loop_data=types.SimpleNamespace(current_tool=tool), context=context)
        hook = module.SystemOneMCPErrorEnd()
        hook.agent = agent
        response = types.SimpleNamespace(message="native child output")

        hook.execute(response=response, tool_name=tool_name)

        self.assertTrue(tool._system1_failed)
        self.assertEqual(response.message, "ERROR: MCP tool reported failure. native child output")

    def test_after_hook_leaves_clean_mcp_result_unmarked(self):
        module = self._load(AFTER, "system_one_mcp_error_clean_test")
        tool_name = "github_mcp_server.get_issue"
        tool = types.SimpleNamespace(name=tool_name, _system1_mcp_log_start=0)
        context = types.SimpleNamespace(log=types.SimpleNamespace(
            logs=[types.SimpleNamespace(type="info", content="ordinary result")]),
            get_data=lambda key: None)
        hook = module.SystemOneMCPErrorEnd()
        hook.agent = types.SimpleNamespace(loop_data=types.SimpleNamespace(current_tool=tool), context=context)
        response = types.SimpleNamespace(message="native output")

        hook.execute(response=response, tool_name=tool_name)

        self.assertFalse(hasattr(tool, "_system1_failed"))
        self.assertEqual(response.message, "native output")


if __name__ == "__main__":
    unittest.main()
