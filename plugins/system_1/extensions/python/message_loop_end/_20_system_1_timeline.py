"""Close a pending S1 step if a host interruption bypassed the decision hook."""

from helpers.extension import Extension
from usr.plugins.system_1.helpers.timeline import finish_main_step


class SystemOneTimelineEnd(Extension):
    async def execute(self, **kwargs):
        if self.agent:
            finish_main_step(self.agent, "Handed off to Main",
                             detail="Decision interrupted or bypassed")
