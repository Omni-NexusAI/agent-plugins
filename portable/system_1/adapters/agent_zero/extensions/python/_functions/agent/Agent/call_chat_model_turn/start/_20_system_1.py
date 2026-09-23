"""Current Agent Zero structured-turn interception point."""

from helpers.extension import Extension
from helpers.llm_result import LLMResult
from usr.plugins.system_1.helpers.runtime import main_decision


class SystemOneMainTurn(Extension):
    async def execute(self, data: dict, **kwargs):
        if not self.agent or data["kwargs"].get("background"):
            return
        action_json = await main_decision(self.agent)
        if not action_json:
            return
        callback = data["kwargs"].get("response_callback")
        if callback:
            await callback(action_json, action_json)
        # Chat-completions mode sends this through process_tools(), then the
        # host's validation, MCP/local resolution, permissions, and history.
        data["result"] = LLMResult.from_chat(response=action_json)
