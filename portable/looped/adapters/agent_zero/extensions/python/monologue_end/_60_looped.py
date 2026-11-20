"""Clear the one-shot /looped arm when the turn ends."""

from helpers.extension import Extension


def _runtime():
    try:
        from usr.plugins.looped.helpers import runtime
    except ImportError:
        from plugins.looped.helpers import runtime
    return runtime


class LoopedTurnEnd(Extension):
    async def execute(self, **kwargs):
        if self.agent:
            _runtime().end_turn(self.agent)
