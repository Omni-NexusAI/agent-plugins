"""Arm a second look at the next step when a tool failed."""

from helpers.extension import Extension


def _runtime():
    try:
        from usr.plugins.looped.helpers import runtime
    except ImportError:
        from plugins.looped.helpers import runtime
    return runtime


class LoopedToolResult(Extension):
    async def execute(self, response=None, **kwargs):
        if self.agent and response is not None:
            _runtime().on_tool_result(self.agent, response)
