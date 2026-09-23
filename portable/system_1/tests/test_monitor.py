import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" / "helpers" / "monitor.py"


class Agent:
    def __init__(self):
        self.intervention = None
        self.data = {}

    def set_data(self, key, value):
        self.data[key] = value

    def get_data(self, key):
        return self.data.get(key)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.enabled = True
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.config_for = lambda agent, role: ({}, {}) if self.enabled else None
        runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=self.choose)
        core = types.ModuleType("usr.plugins.system_1.helpers.system_1_core")
        core.DecisionError = RuntimeError
        self.modules = patch.dict(sys.modules, {runtime.__name__: runtime, core.__name__: core})
        self.modules.start()
        spec = importlib.util.spec_from_file_location("system_one_monitor_test", SOURCE)
        self.monitor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.monitor)

    def tearDown(self):
        self.modules.stop()

    async def choose(self, state, choices):
        return types.SimpleNamespace(choice="host_interrupt", confidence=0.99)

    def test_new_intervention_requests_host_mediation_once(self):
        async def scenario():
            agent = Agent()
            task = asyncio.create_task(self.monitor.monitor(agent, {}, {
                "monitor_interval_seconds": 0.1, "monitor_max_checks": 1,
                "monitor_max_seconds": 1, "min_choice_probability": 0.85}))
            await asyncio.sleep(0.03)
            agent.intervention = "New user direction"
            await asyncio.wait_for(task, timeout=0.5)
            return agent
        agent = asyncio.run(scenario())
        self.assertTrue(agent.get_data(self.monitor.REQUEST_KEY))

    def test_disabling_mode_stops_monitor(self):
        async def scenario():
            agent = Agent()
            task = asyncio.create_task(self.monitor.monitor(agent, {}, {
                "monitor_interval_seconds": 0.1, "monitor_max_checks": 2,
                "monitor_max_seconds": 1}))
            self.enabled = False
            await asyncio.wait_for(task, timeout=0.5)
            return agent
        self.assertFalse(asyncio.run(scenario()).get_data(self.monitor.REQUEST_KEY))


if __name__ == "__main__":
    unittest.main()
