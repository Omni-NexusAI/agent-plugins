from helpers.tool import Response, Tool
from usr.plugins.auxiliary_model_roles.helpers.runtime import delegate


class AuxiliaryDelegate(Tool):
    async def execute(self, role: str = "", goal: str = "", **kwargs) -> Response:
        try:
            result = await delegate(self.agent, role, goal)
            return Response(message=f"{role.title()} specialist result for Main:\n{result}", break_loop=False)
        except Exception as error:
            return Response(message=f"Specialist unavailable or escalated ({type(error).__name__}). Main should continue.", break_loop=False)
