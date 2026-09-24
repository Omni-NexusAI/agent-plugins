from helpers.extension import Extension
from usr.plugins.system_1.helpers.runtime import memory_decision, utility_decision
from usr.plugins.system_1.helpers.utility import install_fixed_utility_response, metrics


class SystemOneUtility(Extension):
    async def execute(self, call_data: dict, **kwargs):
        if self.agent:
            metrics(self.agent)["calls"] += 1
            route = await install_fixed_utility_response(self.agent, call_data)
            if route.bypassed or route.attempted:
                return
            system = call_data.get("system", "")
            if isinstance(system, str):
                if "previous memories are stored" in system:
                    purpose = "retrieval query preparation"
                elif "HISTORY worth memorizing" in system:
                    purpose = "memory ingestion"
                elif "enumerated list of MEMORIES" in system:
                    purpose = "memory retrieval filtering"
                else:
                    purpose = ""
                if purpose and await memory_decision(self.agent, call_data.get("message", ""), purpose) == "precise":
                    call_data["system"] += "\nSystem 1 guidance: keep only facts directly relevant to this task and retain the original meaning."
            await utility_decision(self.agent, call_data)
