from helpers.extension import Extension
from usr.plugins.system_1.helpers.stage_metrics import begin


class SystemOneToolTimingStart(Extension):
    def execute(self, **kwargs):
        if self.agent:
            begin(self.agent, "tool_execution")
