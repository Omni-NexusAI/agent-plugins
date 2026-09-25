from helpers.extension import Extension
from usr.plugins.system_1.helpers.stage_metrics import finish


class SystemOneToolTimingEnd(Extension):
    def execute(self, **kwargs):
        if self.agent:
            finish(self.agent, "tool_execution")
