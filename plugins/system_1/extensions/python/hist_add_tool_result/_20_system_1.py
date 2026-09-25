"""Observe the host's recorded result for a System 1 submitted tool call."""

from helpers.extension import Extension
from usr.plugins.system_1.helpers.runtime import record_host_result


class SystemOneToolResult(Extension):
    def execute(self, data: dict, **kwargs):
        if not self.agent:
            return
        try:
            # The host's own history masking runs after this extension point.
            # Mask before retaining a result or sending it to a decision service.
            from helpers.secrets import get_secrets_manager

            result = data.get("tool_result")
            if not isinstance(result, str):
                return
            masked = get_secrets_manager(self.agent.context).mask_values(result)
            if not isinstance(masked, str):
                return
            observed = record_host_result(
                self.agent,
                data.get("tool_name", ""),
                masked,
            )
            if observed:
                from usr.plugins.system_1.helpers.timeline import record_main_observation
                record_main_observation(self.agent, data.get("tool_name", ""))
        except Exception:
            # Fail closed for result sharing without changing host history.
            return
