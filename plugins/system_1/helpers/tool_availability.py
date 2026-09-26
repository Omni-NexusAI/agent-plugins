"""Read-only availability check for actions submitted to Agent Zero."""

from __future__ import annotations

from pathlib import Path
import re


_NATIVE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_MCP_NAME = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+\Z")


def is_tool_available(agent, tool_name: str) -> bool:
    """Check the host's current tool registry or enabled native tool paths.

    This does not load a tool module, instantiate a tool, or contact an MCP
    server. Agent Zero still resolves, validates, and executes the selected
    tool through its normal path; callers should recheck just before dispatch.
    """
    if not isinstance(tool_name, str) or not tool_name:
        return False

    if "." in tool_name:
        if not _MCP_NAME.fullmatch(tool_name):
            return False
        try:
            from helpers.mcp_handler import MCPConfig

            return bool(MCPConfig.get_for_agent(agent).has_tool(tool_name))
        except Exception:
            return False

    base_name, separator, method = tool_name.partition(":")
    if not _NATIVE_NAME.fullmatch(base_name):
        return False
    if separator and not _NATIVE_NAME.fullmatch(method):
        return False

    try:
        from helpers import subagents

        filename = base_name + ".py"
        return any(
            Path(path).name == filename and Path(path).is_file()
            for path in subagents.get_paths(agent, "tools", filename)
        )
    except Exception:
        return False
