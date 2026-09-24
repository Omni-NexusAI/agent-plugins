from helpers.extension import Extension
from usr.plugins.system_1.helpers.monitor import stop
from usr.plugins.system_1.helpers.runtime import end_turn


class SystemOneMonitorStop(Extension):
    def execute(self, **kwargs):
        if self.agent:
            stop(self.agent)
            try:
                end_turn(self.agent)
            except Exception:
                pass  # Advisory cleanup must not block host completion.
