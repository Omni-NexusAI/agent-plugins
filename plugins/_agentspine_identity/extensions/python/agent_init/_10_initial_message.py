import json

from agent import LoopData
from helpers.extension import Extension
from plugins._agentspine_identity.helpers.identity import apply_identity_text, is_identity_enabled


class InitialMessage(Extension):
    def execute(self, **kwargs):
        """Add the Agentspine-branded greeting for the main agent."""

        if not is_identity_enabled():
            return
        if self.agent.number != 0:
            return
        if self.agent.context.log.logs:
            return

        initial_message = apply_identity_text(
            self.agent.read_prompt("fw.initial_message.md")
        )

        self.agent.loop_data = LoopData(user_message=None)
        self.agent.hist_add_ai_response(initial_message)

        initial_message_json = json.loads(initial_message)
        initial_message_text = initial_message_json.get("tool_args", {}).get(
            "text", "Hello! How can I help you?"
        )

        self.agent.context.log.log(
            type="response",
            content=initial_message_text,
            finished=True,
            update_progress="none",
        )
