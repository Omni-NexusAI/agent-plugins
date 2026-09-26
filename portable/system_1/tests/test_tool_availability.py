"""Availability checks must use host discovery without executing tools."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


SOURCE = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" /
          "helpers" / "tool_availability.py")
SPEC = importlib.util.spec_from_file_location("system_one_tool_availability_test", SOURCE)
availability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(availability)


class ToolAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.agent = object()
        self.paths = []
        self.names = set()
        self.path_calls = []
        self.registry_calls = []
        self.registry_agents = []

        def get_paths(agent, *subpaths):
            self.path_calls.append((agent, subpaths))
            return self.paths

        def has_tool(name):
            self.registry_calls.append(name)
            return name in self.names

        helpers = types.ModuleType("helpers")
        helpers.subagents = types.SimpleNamespace(get_paths=get_paths)
        mcp_handler = types.ModuleType("helpers.mcp_handler")
        def get_for_agent(agent):
            self.registry_agents.append(agent)
            return types.SimpleNamespace(has_tool=has_tool)
        mcp_handler.MCPConfig = types.SimpleNamespace(
            get_for_agent=get_for_agent)
        self.modules = patch.dict(sys.modules, {
            "helpers": helpers, "helpers.mcp_handler": mcp_handler})
        self.modules.start()

    def tearDown(self):
        self.modules.stop()

    def test_enabled_native_path_is_available_without_loading_module(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "memory_load.py"
            path.write_text("raise RuntimeError('must not import tool')")
            self.paths = [str(path)]
            self.assertTrue(availability.is_tool_available(self.agent, "memory_load"))
            self.assertTrue(availability.is_tool_available(self.agent, "memory_load:search"))
        self.assertEqual(self.path_calls, [
            (self.agent, ("tools", "memory_load.py")),
            (self.agent, ("tools", "memory_load.py"))])
        self.assertEqual(self.registry_calls, [])

    def test_unknown_or_stale_native_path_fails_closed(self):
        self.assertFalse(availability.is_tool_available(self.agent, "unknown"))
        with tempfile.TemporaryDirectory() as temp:
            self.paths = [str(Path(temp) / "unknown.py")]
            self.assertFalse(availability.is_tool_available(self.agent, "unknown"))
            other = Path(temp) / "different.py"
            other.write_text("pass")
            self.paths = [str(other)]
            self.assertFalse(availability.is_tool_available(self.agent, "unknown"))

    def test_mcp_uses_cached_registry_and_does_not_fall_back_to_native(self):
        self.names.add("filesystem.read_file")
        self.names.add("server.tool.extra")
        self.assertTrue(availability.is_tool_available(self.agent, "filesystem.read_file"))
        self.assertTrue(availability.is_tool_available(self.agent, "server.tool.extra"))
        self.assertFalse(availability.is_tool_available(self.agent, "filesystem.delete_file"))
        self.assertEqual(self.path_calls, [])
        self.assertEqual(self.registry_calls, ["filesystem.read_file", "server.tool.extra",
                                                "filesystem.delete_file"])
        self.assertEqual(self.registry_agents, [self.agent] * 3)

    def test_malformed_names_never_reach_host_lookup(self):
        for name in (None, "", "../response", "response:bad:name",
                     "response:", "server..tool", "server/tool"):
            with self.subTest(name=name):
                self.assertFalse(availability.is_tool_available(self.agent, name))
        self.assertEqual(self.path_calls, [])
        self.assertEqual(self.registry_calls, [])

    def test_host_lookup_errors_fail_closed(self):
        sys.modules["helpers"].subagents.get_paths = lambda *_: 1 / 0
        self.assertFalse(availability.is_tool_available(self.agent, "response"))
        sys.modules["helpers.mcp_handler"].MCPConfig.get_for_agent = lambda _: 1 / 0
        self.assertFalse(availability.is_tool_available(self.agent, "server.tool"))

    def test_missing_per_agent_registry_fails_closed(self):
        del sys.modules["helpers.mcp_handler"].MCPConfig.get_for_agent
        self.assertFalse(availability.is_tool_available(self.agent, "server.tool"))


if __name__ == "__main__":
    unittest.main()
