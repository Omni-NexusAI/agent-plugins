import json

from helpers.tool import Response, Tool
from usr.plugins.auxiliary_model_roles.helpers.runtime import delegate


class AuxiliaryDelegate(Tool):
    async def execute(self, role: str = "", goal: str = "", **kwargs) -> Response:
        try:
            result = await delegate(self.agent, role, goal)
            if role == "tool":
                try:
                    request = json.loads(result)
                except (ValueError, TypeError):
                    request = None
                if isinstance(request, dict):
                    tool_name = request.get("tool_name")
                    tool_args = request.get("tool_args")
                    if isinstance(tool_name, str) and tool_name not in {"", "response", "auxiliary_delegate"} and isinstance(tool_args, dict):
                        host_execute = getattr(self.agent, "_execute_tool_request", None)
                        if host_execute:
                            await self.agent.validate_tool_request(request)
                            previous = self.agent.history.output_text()
                            outer_tool = self.agent.loop_data.current_tool
                            try:
                                final = await host_execute(tool_name=tool_name, tool_args=tool_args, message=result)
                            finally:
                                self.agent.loop_data.current_tool = outer_tool
                            current = self.agent.history.output_text()
                            report = current[len(previous):].strip() if current.startswith(previous) else ""
                            if not report and final:
                                report = str(final)
                            if not report:
                                report = "The host handled the request; inspect the tool log for its result."
                            return Response(message=f"Tool specialist host action result for Main:\n{report[:8000]}", break_loop=False)
            return Response(message=f"{role.title()} specialist result for Main:\n{result}", break_loop=False)
        except Exception as error:
            return Response(message=f"Specialist unavailable or escalated ({type(error).__name__}). Main should continue.", break_loop=False)
