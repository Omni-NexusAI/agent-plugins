"""Observe the host's recorded result for a System 1 submitted tool call."""

import json

from helpers.extension import Extension
from usr.plugins.system_1.helpers.runtime import (record_host_result,
                                                  record_main_host_action)


def _successful_recorded_result(value: str) -> bool:
    """Do not suppress a retry when the host explicitly recorded an error."""
    stripped = value.lstrip()
    if stripped.casefold().startswith(("error:", "failed:", "failure:")):
        return False
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            return True
        if isinstance(payload, dict) and (payload.get("isError") is True or
                payload.get("status") in {"error", "failed", "cancelled", "timeout"}):
            return False
    return True


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
            tool = getattr(getattr(self.agent, "loop_data", None),
                           "current_tool", None)
            succeeded = (_successful_recorded_result(masked) and
                         getattr(tool, "_system1_failed", False) is not True)
            observed = record_host_result(
                self.agent,
                data.get("tool_name", ""),
                masked,
                succeeded=succeeded,
            )
            if observed and data.get("tool_name") != "parallel":
                if succeeded:
                    from usr.plugins.system_1.helpers.timeline import record_main_observation
                    record_main_observation(self.agent, data.get("tool_name", ""))
                else:
                    from usr.plugins.system_1.helpers.timeline import record_main_event
                    record_main_event(self.agent, "tool_failed",
                                      tool_name=data.get("tool_name", ""))
            elif not observed:
                args = getattr(tool, "args", None)
                name = data.get("tool_name", "")
                if (getattr(tool, "name", None) == name and
                        isinstance(args, dict)):
                    record_main_host_action(self.agent, name, args,
                                            succeeded=succeeded)
        except Exception:
            # Fail closed for result sharing without changing host history.
            return
