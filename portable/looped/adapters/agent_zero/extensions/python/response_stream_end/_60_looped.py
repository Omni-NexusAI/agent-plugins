"""Show the winning step in the chat when it replaced the streamed one."""

from helpers.extension import Extension


def _runtime():
    try:
        from usr.plugins.looped.helpers import runtime
    except ImportError:
        from plugins.looped.helpers import runtime
    return runtime


class LoopedStreamEnd(Extension):
    async def execute(self, loop_data=None, **kwargs):
        if self.agent and loop_data is not None:
            await _runtime().on_stream_end(self.agent, loop_data)
