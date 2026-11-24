from helpers.extension import Extension
from usr.plugins.initial_greeting_guard.helpers.seed import model_history


class OmitInitialSeed(Extension):
    def execute(self, loop_data, **kwargs):
        if self.agent is not None and self.agent.number == 0:
            loop_data.history_output = model_history(loop_data.history_output)
