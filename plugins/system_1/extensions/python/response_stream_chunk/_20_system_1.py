from helpers.extension import Extension
from usr.plugins.system_1.helpers.monitor import REQUEST_KEY


class SystemOneMonitorRequest(Extension):
    async def execute(self, **kwargs):
        if not self.agent or not self.agent.get_data(REQUEST_KEY):
            return
        self.agent.set_data(REQUEST_KEY, False)
        # The native method performs the actual intervention and history update.
        if self.agent.intervention:
            await self.agent.handle_intervention()
