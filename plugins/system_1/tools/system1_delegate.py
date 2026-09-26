"""Let foreground Main hand a bounded choice back to System 1."""

from helpers.tool import Response, Tool


class System1Delegate(Tool):
    async def execute(self, **kwargs) -> Response:
        arguments = {**self.args, **kwargs}
        action_ids = arguments.get("action_ids")
        if (not isinstance(action_ids, list) or not 1 <= len(action_ids) <= 8 or
                any(not isinstance(value, str) or not value for value in action_ids)):
            return Response(message="System 1 delegation needs one to eight eligible action IDs.",
                            break_loop=False)
        from usr.plugins.system_1.helpers.runtime import record_main_delegation

        accepted = record_main_delegation(self.agent, action_ids, goal=arguments.get("goal"))
        return Response(
            message=("System 1 will choose from the delegated eligible actions next."
                     if accepted else
                     "System 1 delegation was unavailable; Main should continue."),
            break_loop=False,
        )
