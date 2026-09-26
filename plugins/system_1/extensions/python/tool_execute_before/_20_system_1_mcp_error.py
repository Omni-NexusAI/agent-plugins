"""Capture the log boundary for an Agent Zero MCP call's error signal."""

from helpers.extension import Extension


class SystemOneMCPErrorStart(Extension):
    def execute(self, tool_name="", **kwargs):
        if not self.agent or not isinstance(tool_name, str) or "." not in tool_name:
            return
        tool = getattr(getattr(self.agent, "loop_data", None), "current_tool", None)
        logs = getattr(getattr(self.agent.context, "log", None), "logs", None)
        if tool is not None and getattr(tool, "name", None) == tool_name and isinstance(logs, list):
            tool._system1_mcp_log_start = len(logs)
