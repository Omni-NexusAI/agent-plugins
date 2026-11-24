from helpers.extension import Extension


class NativeToolEnvelope(Extension):
    def execute(self, call_data, **kwargs):
        if self.agent is None or not isinstance(call_data, dict):
            return
        if any(call_data.get(key) for key in ("a0_responses_function_tools", "a0_chat_function_tools", "tools")):
            return
        from helpers.plugins import get_plugin_config
        from usr.plugins.native_tool_output_contract.helpers.contract import prepare_model
        call_data["model"] = prepare_model(
            call_data.get("model"), get_plugin_config("native_tool_output_contract", self.agent) or {}
        )
