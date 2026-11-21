"""Structured-turn hosts: optionally start the second sample in parallel."""

from helpers.extension import Extension


def _runtime():
    try:
        from usr.plugins.looped.helpers import runtime
    except ImportError:
        from plugins.looped.helpers import runtime
    return runtime


class LoopedTurnCallStart(Extension):
    async def execute(self, data=None, **kwargs):
        if self.agent and isinstance(data, dict):
            await _runtime().on_call_start(self.agent, data)
