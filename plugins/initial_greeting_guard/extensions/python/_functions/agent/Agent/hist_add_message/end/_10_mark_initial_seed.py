"""Mark only source-verified legacy/v2.15 synthetic initialization records."""
from helpers.extension import Extension
from usr.plugins.initial_greeting_guard.helpers.seed import mark_created_pair


class MarkInitialSeed(Extension):
    def execute(self, data, **kwargs):
        if not data.get("exception"):
            mark_created_pair(self.agent, data.get("result"))
