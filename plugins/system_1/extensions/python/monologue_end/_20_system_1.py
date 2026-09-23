from helpers.extension import Extension
from usr.plugins.system_1.helpers.monitor import stop


class SystemOneMonitorStop(Extension):
    def execute(self, **kwargs):
        if self.agent:
            stop(self.agent)
