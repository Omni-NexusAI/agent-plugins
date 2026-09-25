from helpers.extension import Extension
from usr.plugins.system_1.helpers.utility import install_fixed_utility_response, metrics
try:
    from usr.plugins.system_1.helpers.utility import (
        install_embedding_memory_guidance, install_memory_utility_response,
        install_utility_measurement)
except ImportError:  # A hot reload may briefly see the prior helper module.
    install_embedding_memory_guidance = None
    install_memory_utility_response = None
    install_utility_measurement = None


class SystemOneUtility(Extension):
    async def execute(self, call_data: dict, **kwargs):
        if self.agent:
            metrics(self.agent)["calls"] += 1
            route = await install_fixed_utility_response(self.agent, call_data)
            if route.bypassed:
                return
            if route.attempted:
                if install_utility_measurement:
                    install_utility_measurement(self.agent, call_data, outcome="fallback")
                return
            memory_route = (await install_memory_utility_response(self.agent, call_data)
                            if install_memory_utility_response else route)
            if memory_route.bypassed:
                return
            if install_embedding_memory_guidance:
                await install_embedding_memory_guidance(self.agent, call_data)
            if install_utility_measurement:
                install_utility_measurement(
                    self.agent, call_data,
                    outcome="fallback" if memory_route.attempted else "ordinary")
