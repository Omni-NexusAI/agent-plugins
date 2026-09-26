"""Place the System 1 decision step before Agent Zero's native GEN step."""

from helpers.extension import Extension
from usr.plugins.system_1.helpers.timeline import start_main_step


class SystemOneTimeline(Extension):
    async def execute(self, **kwargs):
        if self.agent:
            start_main_step(self.agent)
