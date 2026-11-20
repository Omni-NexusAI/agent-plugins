"""Structured-turn hosts: check the step and replace it when another pass wins."""

from helpers.extension import Extension


def _runtime():
    try:
        from usr.plugins.looped.helpers import runtime
    except ImportError:
        from plugins.looped.helpers import runtime
    return runtime


class LoopedTurnCallEnd(Extension):
    async def execute(self, data=None, **kwargs):
        if self.agent and isinstance(data, dict):
            await _runtime().on_call_end(self.agent, data, turn=True)
