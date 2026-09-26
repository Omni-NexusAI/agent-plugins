"""Carry the completed System 1 action ledger into foreground Main calls."""

from helpers.extension import Extension
from usr.plugins.system_1.helpers.runtime import main_handoff_note


class SystemOneMainHandoff(Extension):
    def execute(self, call_data: dict, **kwargs):
        if not self.agent or call_data.get("background"):
            return
        note = main_handoff_note(self.agent)
        messages = call_data.get("messages")
        if not note or not isinstance(messages, list):
            return
        from langchain_core.messages import SystemMessage
        messages.append(SystemMessage(content=note))
