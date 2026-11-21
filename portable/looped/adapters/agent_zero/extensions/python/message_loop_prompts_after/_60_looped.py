"""Add the task re-read block, the retry note and the merged plan to the prompt."""

from helpers.extension import Extension


def _runtime():
    try:
        from usr.plugins.looped.helpers import runtime
    except ImportError:
        from plugins.looped.helpers import runtime
    return runtime


class LoopedPrompt(Extension):
    async def execute(self, loop_data=None, **kwargs):
        if self.agent and loop_data is not None:
            await _runtime().on_prompt(self.agent, loop_data)
