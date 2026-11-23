"""Reset looped-mode state when a turn starts."""

from helpers.extension import Extension


def _runtime():
    try:
        from usr.plugins.looped.helpers import runtime
    except ImportError:
        from plugins.looped.helpers import runtime
    return runtime


class LoopedTurnStart(Extension):
    async def execute(self, **kwargs):
        if self.agent:
            _runtime().begin_turn(self.agent)
