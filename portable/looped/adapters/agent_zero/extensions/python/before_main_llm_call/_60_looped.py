"""Mark the message loop's own model call so only that call is checked."""

from helpers.extension import Extension


def _runtime():
    try:
        from usr.plugins.looped.helpers import runtime
    except ImportError:
        from plugins.looped.helpers import runtime
    return runtime


class LoopedMarkMainCall(Extension):
    async def execute(self, loop_data=None, **kwargs):
        if self.agent and loop_data is not None:
            _runtime().mark_main_call(self.agent, loop_data)
