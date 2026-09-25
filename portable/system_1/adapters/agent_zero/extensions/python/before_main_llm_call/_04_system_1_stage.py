from helpers.extension import Extension
from usr.plugins.system_1.helpers.stage_metrics import finish


class SystemOnePromptTimingEnd(Extension):
    def execute(self, **kwargs):
        if self.agent:
            finish(self.agent, "prompt_preparation")
