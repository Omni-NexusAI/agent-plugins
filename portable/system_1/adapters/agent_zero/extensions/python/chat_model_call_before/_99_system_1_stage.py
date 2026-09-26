from helpers.extension import Extension
from usr.plugins.system_1.helpers.stage_metrics import begin


class SystemOneMainTimingStart(Extension):
    def execute(self, call_data: dict, **kwargs):
        if self.agent and isinstance(call_data, dict):
            begin(self.agent, "main_background" if call_data.get("background")
                  else "main_foreground", call_data)
