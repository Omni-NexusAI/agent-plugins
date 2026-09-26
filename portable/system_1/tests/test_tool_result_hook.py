import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" /
          "extensions" / "python" / "hist_add_tool_result" / "_20_system_1.py")


class ToolResultHookTests(unittest.TestCase):
    def _load_main_action_hook(self, *, observed):
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {})
        secrets = types.ModuleType("helpers.secrets")
        secrets.get_secrets_manager = lambda context: types.SimpleNamespace(mask_values=lambda value: value)
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.record_host_result = lambda *args, **kwargs: observed
        calls = []
        runtime.record_main_host_action = lambda *args, **kwargs: calls.append((args, kwargs)) or True
        modules = patch.dict(sys.modules, {extension.__name__: extension,
                                           secrets.__name__: secrets,
                                           runtime.__name__: runtime})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location("system_1_main_action_hook", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hook = module.SystemOneToolResult()
        hook.agent = types.SimpleNamespace(
            context=object(),
            loop_data=types.SimpleNamespace(current_tool=types.SimpleNamespace(
                name="memory_load", args={"query": "current project"})),
        )
        return hook, calls

    def test_accepted_result_adds_safe_observation_marker(self):
        observations = []
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {})
        secrets = types.ModuleType("helpers.secrets")
        secrets.get_secrets_manager = lambda context: types.SimpleNamespace(
            mask_values=lambda value: value.replace("private", "***"))
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.record_host_result = lambda *args, **kwargs: args[2] == "Found *** skills"
        runtime.record_main_host_action = lambda *args, **kwargs: None
        timeline = types.ModuleType("usr.plugins.system_1.helpers.timeline")
        timeline.record_main_observation = lambda agent, name: observations.append(name)
        with patch.dict(sys.modules, {extension.__name__: extension,
                                      secrets.__name__: secrets,
                                      runtime.__name__: runtime,
                                      timeline.__name__: timeline}):
            spec = importlib.util.spec_from_file_location("system_1_result_marker_hook", SOURCE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            hook = module.SystemOneToolResult()
            hook.agent = types.SimpleNamespace(context=object())
            hook.execute({"tool_name": "skills_tool", "tool_result": "Found private skills"})
        self.assertEqual(observations, ["skills_tool"])

    def test_passes_host_recorded_result_without_changing_payload(self):
        calls = []
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {})
        secrets = types.ModuleType("helpers.secrets")
        secrets.get_secrets_manager = lambda context: types.SimpleNamespace(
            mask_values=lambda value: value.replace("private", "***"))
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.record_host_result = lambda *args, **kwargs: calls.append((args, kwargs))
        runtime.record_main_host_action = lambda *args, **kwargs: None
        with patch.dict(sys.modules, {extension.__name__: extension,
                                      secrets.__name__: secrets,
                                      runtime.__name__: runtime}):
            spec = importlib.util.spec_from_file_location("system_1_tool_result_hook", SOURCE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            hook = module.SystemOneToolResult()
            hook.agent = types.SimpleNamespace(context=object())
            data = {"tool_name": "skills_tool", "tool_result": "Found private skills"}
            hook.execute(data)
        self.assertEqual(calls, [
            ((hook.agent, "skills_tool", "Found *** skills"), {"succeeded": True})])
        self.assertEqual(data, {"tool_name": "skills_tool", "tool_result": "Found private skills"})

    def test_observer_failure_does_not_change_host_result(self):
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {})
        secrets = types.ModuleType("helpers.secrets")
        secrets.get_secrets_manager = lambda context: types.SimpleNamespace(
            mask_values=lambda value: value)
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")

        def fail(*args):
            raise RuntimeError("observer failed")

        runtime.record_host_result = fail
        runtime.record_main_host_action = lambda *args, **kwargs: None
        with patch.dict(sys.modules, {extension.__name__: extension,
                                      secrets.__name__: secrets,
                                      runtime.__name__: runtime}):
            spec = importlib.util.spec_from_file_location("system_1_tool_result_hook", SOURCE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            hook = module.SystemOneToolResult()
            hook.agent = types.SimpleNamespace(context=object())
            data = {"tool_name": "skills_tool", "tool_result": "Found 2 skills"}
            hook.execute(data)
        self.assertEqual(data["tool_result"], "Found 2 skills")

    def test_mask_failure_does_not_record_raw_result(self):
        calls = []
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {})
        secrets = types.ModuleType("helpers.secrets")

        def unavailable(context):
            raise RuntimeError("secrets manager unavailable")

        secrets.get_secrets_manager = unavailable
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.record_host_result = lambda *args: calls.append(args)
        runtime.record_main_host_action = lambda *args, **kwargs: None
        with patch.dict(sys.modules, {extension.__name__: extension,
                                      secrets.__name__: secrets,
                                      runtime.__name__: runtime}):
            spec = importlib.util.spec_from_file_location("system_1_tool_result_hook", SOURCE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            hook = module.SystemOneToolResult()
            hook.agent = types.SimpleNamespace(context=object())
            hook.execute({"tool_name": "skills_tool", "tool_result": "private"})
        self.assertEqual(calls, [])

    def test_successful_foreground_main_result_records_a_dedupe_signature(self):
        hook, calls = self._load_main_action_hook(observed=False)

        hook.execute({"tool_name": "memory_load", "tool_result": "project context"})

        self.assertEqual(calls, [
            ((hook.agent, "memory_load", {"query": "current project"}), {"succeeded": True})])

    def test_failed_foreground_main_result_keeps_that_call_retryable(self):
        hook, calls = self._load_main_action_hook(observed=False)

        hook.execute({"tool_name": "memory_load", "tool_result": "Error: service unavailable"})

        self.assertEqual(calls, [
            ((hook.agent, "memory_load", {"query": "current project"}), {"succeeded": False})])

    def test_failed_system1_result_records_failure_transition_not_next_decision_observation(self):
        transitions = []
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {})
        secrets = types.ModuleType("helpers.secrets")
        secrets.get_secrets_manager = lambda context: types.SimpleNamespace(mask_values=lambda value: value)
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.record_host_result = lambda *args, **kwargs: True
        runtime.record_main_host_action = lambda *args, **kwargs: None
        timeline = types.ModuleType("usr.plugins.system_1.helpers.timeline")
        timeline.record_main_event = lambda agent, kind, **kwargs: transitions.append((kind, kwargs))
        with patch.dict(sys.modules, {extension.__name__: extension,
                                      secrets.__name__: secrets,
                                      runtime.__name__: runtime,
                                      timeline.__name__: timeline}):
            spec = importlib.util.spec_from_file_location("system_1_failed_result_hook", SOURCE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            hook = module.SystemOneToolResult()
            hook.agent = types.SimpleNamespace(
                context=object(),
                loop_data=types.SimpleNamespace(current_tool=types.SimpleNamespace(
                    name="github_mcp_server.get_file_contents", args={})),
            )
            hook.execute({"tool_name": "github_mcp_server.get_file_contents",
                          "tool_result": '{"isError":true,"error":"missing"}'})

        self.assertEqual(transitions, [("tool_failed", {
            "tool_name": "github_mcp_server.get_file_contents"})])

    def test_system1_owned_result_is_not_misattributed_to_main(self):
        hook, calls = self._load_main_action_hook(observed=True)

        hook.execute({"tool_name": "memory_load", "tool_result": "system one result"})

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
