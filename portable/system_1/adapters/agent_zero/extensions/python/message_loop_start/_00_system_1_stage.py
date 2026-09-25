from helpers.extension import Extension
from usr.plugins.system_1.helpers.stage_metrics import begin


class SystemOnePromptTimingStart(Extension):
    def execute(self, **kwargs):
        if self.agent:
            begin(self.agent, "prompt_preparation")
