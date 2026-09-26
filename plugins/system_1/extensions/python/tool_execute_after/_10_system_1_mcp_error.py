"""Preserve native MCP failure information for System 1 observations."""

from helpers.extension import Extension


class SystemOneMCPErrorEnd(Extension):
    def execute(self, response=None, tool_name="", **kwargs):
        if (not self.agent or response is None or
                not isinstance(tool_name, str) or "." not in tool_name):
            return
        tool = getattr(getattr(self.agent, "loop_data", None), "current_tool", None)
        start = getattr(tool, "_system1_mcp_log_start", None)
        logs = getattr(getattr(self.agent.context, "log", None), "logs", None)
        if (getattr(tool, "name", None) != tool_name or type(start) is not int or
                not isinstance(logs, list) or not 0 <= start <= len(logs)):
            return
        failed = any(
            getattr(item, "type", None) == "warning" and
            isinstance(getattr(item, "content", None), str) and
            item.content.startswith(tool_name + ": ")
            for item in logs[start:]
        )
        if not failed:
            return
        tool._system1_failed = True
        # Native parallel returns only each child's Response.message, not its
        # MCP isError flag. Mark a failed child in that text so the parent's
        # validated result parser cannot mistake it for successful evidence.
        if self.agent.context.get_data("_parallel_job_id"):
            message = getattr(response, "message", "")
            response.message = "ERROR: MCP tool reported failure. " + str(message)
