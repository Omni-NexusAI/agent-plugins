from helpers.extension import Extension
from usr.plugins.system_1.helpers.monitor import start


class SystemOneMonitorStart(Extension):
    def execute(self, **kwargs):
        if self.agent:
            start(self.agent)
