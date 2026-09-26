from helpers.extension import Extension
from usr.plugins.system_1.helpers.runtime import main_decision


class SystemOneMain(Extension):
    async def execute(self, data: dict, **kwargs):
        if self.agent and not data["kwargs"].get("background"):
            action_json = await main_decision(self.agent)
            if action_json:
                callback = data["kwargs"].get("response_callback")
                if callback:
                    await callback(action_json, action_json)
                data["result"] = (action_json, "")
