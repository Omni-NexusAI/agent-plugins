import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" / "helpers" / "runtime.py"


class Agent:
    loop_data = types.SimpleNamespace(iteration=0)
    last_user_message = types.SimpleNamespace(output_text=lambda: "Inspect this page")


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = {"main": {"enabled": True, "backend": "jev", "model": "jev-latest"},
                       "policy": {"action_precedence": "tool_first", "actions": {}}}
        helpers = types.ModuleType("helpers")
        helpers.plugins = types.SimpleNamespace(get_plugin_config=lambda _name, _agent: self.config)
        core = types.ModuleType("usr.plugins.system_1.helpers.system_1_core")
        core.DecisionClient = object
        core.DecisionError = RuntimeError
        decision = types.ModuleType(core.__name__ + ".decision")
        decision.selected_action = lambda *args, **kwargs: None
        timeline = types.ModuleType("usr.plugins.system_1.helpers.timeline")
        self.timeline_events = []
        timeline.finish_main_step = lambda *args, **kwargs: self.timeline_events.append((args, kwargs))
        timeline.record_main_event = lambda *args, **kwargs: self.timeline_events.append((args, kwargs))
        tool_availability = types.ModuleType("usr.plugins.system_1.helpers.tool_availability")
        tool_availability.is_tool_available = lambda agent, tool_name: True
        parallel_source = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" /
                           "helpers" / "parallel_results.py")
        parallel_spec = importlib.util.spec_from_file_location(
            "usr.plugins.system_1.helpers.parallel_results", parallel_source)
        parallel_results = importlib.util.module_from_spec(parallel_spec)
        parallel_spec.loader.exec_module(parallel_results)
        auxiliary = types.ModuleType("usr.plugins.auxiliary_model_roles.helpers.runtime")
        auxiliary.available_roles = lambda agent: {"tool": {"enabled": True}}
        self.modules = patch.dict(sys.modules, {"helpers": helpers, core.__name__: core,
                                                 decision.__name__: decision, timeline.__name__: timeline,
                                                 tool_availability.__name__: tool_availability,
                                                 parallel_results.__name__: parallel_results,
                                                 auxiliary.__name__: auxiliary})
        self.modules.start()
        spec = importlib.util.spec_from_file_location("system_one_runtime_test", SOURCE)
        self.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runtime)

    def tearDown(self):
        self.modules.stop()

    def test_main_correction_is_never_partially_forwarded(self):
        state = {"main_guidance": "", "actions_submitted": 0,
                 "main_started_actions": 0}
        guidance = "use the validated result " * 110
        self.runtime._consume_main_result(state, {"kind": "correction", "text": guidance})
        self.assertEqual(state["main_guidance"], guidance)
        with self.assertRaises(RuntimeError):
            self.runtime._decision_state("request", [], {}, 128, guidance)

    def test_main_handoff_uses_only_current_host_observation_names(self):
        action = {"tool_name": "github_mcp_server.get_pull_request_status",
                  "tool_args": {"pull_number": 11}}
        self.config["policy"]["actions"] = {"status": action}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=2)
        state = self.runtime._turn_state(agent, create=True)
        state["complete"] = True
        state["observations"].append({
            "action_id": "status", "action_definition": action,
            "tool_name": action["tool_name"], "result": "private-result-marker"})
        note = self.runtime.main_handoff_note(agent)
        self.assertIn("already executed 1 selected tool call", note)
        self.assertIn(action["tool_name"], note)
        self.assertIn("clear final answer", note)
        self.assertNotIn("private-result-marker", note)
        agent.last_user_message = types.SimpleNamespace(output_text=lambda: "New request")
        self.assertEqual(self.runtime.main_handoff_note(agent), "")

    def test_main_handoff_disappears_if_action_policy_changes(self):
        action = {"tool_name": "memory_load", "tool_args": {"query": "safe"}}
        self.config["policy"]["actions"] = {"lookup": action}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=1)
        state = self.runtime._turn_state(agent, create=True)
        state["complete"] = True
        state["observations"].append({
            "action_id": "lookup", "action_definition": action,
            "tool_name": "memory_load", "result": "observed"})
        self.config["policy"]["actions"]["lookup"] = {
            "tool_name": "memory_load", "tool_args": {"query": "changed"}}
        self.assertEqual(self.runtime.main_handoff_note(agent), "")

    def test_main_handoff_includes_bounded_permitted_host_evidence(self):
        action = {"tool_name": "github_mcp_server.get_pull_request_status",
                  "tool_args": {"pull_number": 11},
                  "share_result_with_backend": True}
        self.config["policy"]["actions"] = {"status": action}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=2)
        state = self.runtime._turn_state(agent, create=True)
        state["complete"] = True
        state["observations"].append({
            "action_id": "status", "action_definition": action,
            "tool_name": action["tool_name"],
            "result": "observed-status-" + "x" * 2000,
            "truncated": False,
        })
        note = self.runtime.main_handoff_note(agent)
        self.assertIn("observed-status-", note)
        self.assertIn('"truncated":true', note)
        self.assertNotIn("x" * 1201, note)

    def test_oversized_main_advisory_is_not_sent_truncated(self):
        agent = Agent()
        called = []
        async def fake_call(**kwargs):
            called.append(kwargs)
            return ('{"kind":"correction","text":"ok"}', "")
        agent.call_chat_model = fake_call
        module = types.ModuleType("langchain_core.messages")
        module.HumanMessage = lambda content: content
        module.SystemMessage = lambda content: content
        with patch.dict(sys.modules, {"langchain_core": types.ModuleType("langchain_core"),
                                      "langchain_core.messages": module}):
            result = asyncio.run(self.runtime._run_main_correction(agent, "x" * 4001, 1))
        self.assertIsNone(result)
        self.assertFalse(called)

    def test_tool_first_uses_normal_host_delegation_tool(self):
        result = asyncio.run(self.runtime.main_decision(Agent()))
        self.assertEqual(json.loads(result), {"tool_name": "auxiliary_delegate",
                                               "tool_args": {"role": "tool", "goal": "Inspect this page"}})
        self.assertEqual(self.timeline_events[-1][0][1], "Delegated to Tool")

    def test_disabled_main_escalates(self):
        self.config["main"]["enabled"] = False
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))

    def test_later_iterations_leave_tool_results_to_host(self):
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=1)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))

    def test_disabling_during_backend_call_prevents_late_dispatch(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {"memory": {"tool_name": "memory_load", "tool_args": {"query": "test"}}}
        async def decide(state, choices):
            self.config["main"]["enabled"] = False
            return types.SimpleNamespace(choice="memory", confidence=0.99)
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))
        self.assertEqual(self.timeline_events[-1][1]["detail"], "Mode disabled during decision")

    def test_eligible_action_names_host_tool_in_timeline(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "recall": {"tool_name": "memory_load", "tool_args": {"query": "current project"}}}
        async def decide(state, choices):
            return types.SimpleNamespace(choice="recall", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions["recall"]
        result = asyncio.run(self.runtime.main_decision(Agent()))
        self.assertEqual(json.loads(result)["tool_name"], "memory_load")
        self.assertEqual(self.timeline_events[-1][1]["action_name"], "memory_load")

    def test_low_confidence_action_handoff_explains_threshold(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["min_choice_probability"] = 0.5
        self.config["policy"]["actions"] = {
            "recall": {"tool_name": "memory_load", "tool_args": {"query": "current project"}}}

        async def decide(state, choices):
            return types.SimpleNamespace(choice="recall", confidence=0.47, backend="jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))
        self.assertEqual(self.timeline_events[-1][0][1], "Handed off to Main")
        self.assertEqual(self.timeline_events[-1][1]["detail"],
                         "Decision confidence below action threshold")

    def test_host_result_drives_next_decision_without_replaying_action(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "memory_load", "tool_args": {"query": "project"},
                       "share_result_with_backend": True, "return_result_to_user": True}}
        states = []
        async def decide(state, choices):
            states.append((state, list(choices)))
            return types.SimpleNamespace(choice="lookup" if len(states) == 1 else "finish",
                                         confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        first = asyncio.run(self.runtime.main_decision(agent))
        self.assertEqual(json.loads(first)["tool_name"], "memory_load")
        self.assertFalse(self.runtime.should_decide(agent))
        self.assertFalse(self.runtime.record_host_result(agent, "other_tool", "wrong result"))
        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "Project fact"))
        agent.loop_data.iteration = 1
        self.assertTrue(self.runtime.should_decide(agent))
        second = asyncio.run(self.runtime.main_decision(agent))
        self.assertEqual(json.loads(second), {"tool_name": "response",
                                              "tool_args": {"text": "Project fact"}})
        self.assertIn("Project fact", states[1][0])
        self.assertNotIn("lookup", states[1][1])
        self.assertFalse(self.runtime.should_decide(agent))

    def test_new_monologue_discards_pending_result_and_action_budget(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "memory_load", "tool_args": {"query": "project"}}}
        async def decide(state, choices):
            return types.SimpleNamespace(choice="lookup", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertTrue(self.runtime.should_decide(agent))
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))

    def test_result_content_is_withheld_by_default(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "memory_load", "tool_args": {"query": "project"}},
            "next": {"tool_name": "memory_load", "tool_args": {"query": "next"}}}
        states = []
        async def decide(state, choices):
            states.append(state)
            return types.SimpleNamespace(choice="lookup" if len(states) == 1 else "main",
                                         confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "PRIVATE TOOL OUTPUT"))
        agent.loop_data.iteration = 1
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertNotIn("PRIVATE TOOL OUTPUT", states[1])

    def test_revoked_result_permission_is_checked_before_next_backend_call(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "memory_load", "tool_args": {"query": "project"},
                       "share_result_with_backend": True},
            "next": {"tool_name": "memory_load", "tool_args": {"query": "next"}}}
        states = []

        async def decide(state, choices):
            states.append(state)
            return types.SimpleNamespace(choice="lookup" if len(states) == 1 else "main",
                                         confidence=0.99, backend="jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "TOOL_RESULT_SENTINEL"))
        self.config["policy"]["actions"]["lookup"]["share_result_with_backend"] = False
        agent.loop_data.iteration = 1
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertNotIn("TOOL_RESULT_SENTINEL", states[1])

    def test_oversized_follow_up_hands_to_main_without_losing_evidence(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["max_state_chars"] = 256
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "memory_load", "tool_args": {"query": "project"},
                       "share_result_with_backend": True},
            "next": {"tool_name": "memory_load", "tool_args": {"query": "next"}}}
        states = []

        async def decide(state, choices):
            states.append(state)
            return types.SimpleNamespace(choice="lookup" if len(states) == 1 else "main",
                                         confidence=0.99, backend="jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        agent.last_user_message = types.SimpleNamespace(output_text=lambda: "USER_TASK_SENTINEL")
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "R" * 520))
        agent.loop_data.iteration = 1
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertEqual(len(states), 1)
        self.assertEqual(self.timeline_events[-1][0][1], "Handed off to Main")

    def test_request_field_binds_typed_argument(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "memory_load", "tool_args": {},
                       "argument_bindings": {"query": {"source": "request",
                           "prefix": "Load issue ", "suffix": "", "value_type": "integer"}}}}
        async def decide(state, choices):
            return types.SimpleNamespace(choice="lookup", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        agent.last_user_message = types.SimpleNamespace(output_text=lambda: "Load issue 17")
        action = asyncio.run(self.runtime.main_decision(agent))
        self.assertEqual(json.loads(action)["tool_args"], {"query": 17})

    def test_result_field_binds_dependent_action_after_host_record(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "search": {"tool_name": "memory_load", "tool_args": {"query": "project"},
                       "allow_result_bindings": True},
            "detail": {"tool_name": "memory_load", "tool_args": {},
                       "argument_bindings": {"query": {"source": "result",
                           "from_action": "search", "path": ["items", 0, "id"],
                           "value_type": "integer"}}}}
        choices_seen = []
        async def decide(state, choices):
            choices_seen.append(set(choices))
            return types.SimpleNamespace(choice="search" if len(choices_seen) == 1 else "detail",
                                         confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertEqual(json.loads(asyncio.run(self.runtime.main_decision(agent)))["tool_args"],
                         {"query": "project"})
        self.assertNotIn("detail", choices_seen[0])
        self.assertTrue(self.runtime.record_host_result(
            agent, "memory_load", '{"items":[{"id":17}]}'))
        agent.loop_data.iteration = 1
        second = asyncio.run(self.runtime.main_decision(agent))
        self.assertEqual(json.loads(second)["tool_args"], {"query": 17})
        self.assertIn("detail", choices_seen[1])
        self.assertFalse(self.runtime.should_decide(agent))

    def test_successive_results_remain_in_decider_state(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            name: {"tool_name": "memory_load", "tool_args": {"query": name},
                   "share_result_with_backend": True}
            for name in ("first", "second", "third")}
        states = []
        async def decide(state, choices):
            states.append(state)
            return types.SimpleNamespace(choice={1: "first", 2: "second", 3: "main"}[len(states)],
                                         confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "FIRST_SENTINEL"))
        agent.loop_data.iteration = 1
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "SECOND_SENTINEL"))
        agent.loop_data.iteration = 2
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertIn("FIRST_SENTINEL", states[2])
        self.assertIn("SECOND_SENTINEL", states[2])

    def test_revoked_binding_permission_hands_off(self):
        self.config["policy"]["action_precedence"] = "main_first"
        search = {"tool_name": "memory_load", "tool_args": {"query": "project"},
                  "allow_result_bindings": True}
        self.config["policy"]["actions"] = {
            "search": search,
            "detail": {"tool_name": "memory_load", "tool_args": {},
                       "argument_bindings": {"query": {"source": "result",
                           "from_action": "search", "path": ["id"],
                           "value_type": "integer"}}}}
        async def decide(state, choices):
            return types.SimpleNamespace(choice="search", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", '{"id":17}'))
        search["allow_result_bindings"] = False
        agent.loop_data.iteration = 1
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))

    def test_mcp_result_never_finishes_as_raw_response(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "github_mcp_server.get_pull_request_status",
                       "tool_args": {"pull_request_number": 11},
                       "return_result_to_user": True}}
        async def decide(state, choices):
            return types.SimpleNamespace(choice="lookup", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(self.runtime.record_host_result(
            agent, "github_mcp_server.get_pull_request_status", '{"state":"OPEN"}'))
        agent.loop_data.iteration = 1
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))

    def test_changed_action_during_decision_cannot_dispatch(self):
        self.config["policy"]["action_precedence"] = "main_first"
        action = {"tool_name": "memory_load", "tool_args": {"query": "safe"}}
        self.config["policy"]["actions"] = {"lookup": action}
        async def decide(state, choices):
            action["tool_args"]["query"] = "changed"
            return types.SimpleNamespace(choice="lookup", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))

    def test_reduced_action_cap_prevents_late_dispatch(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "one": {"tool_name": "memory_load", "tool_args": {"query": "one"}},
            "two": {"tool_name": "memory_load", "tool_args": {"query": "two"}}}
        calls = 0
        async def decide(state, choices):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.config["policy"]["max_actions_per_turn"] = 1
            return types.SimpleNamespace(choice="one" if calls == 1 else "two",
                                         confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        self.assertIsNotNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "one result"))
        agent.loop_data.iteration = 1
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))

    def test_reserved_decision_ids_are_not_actions(self):
        self.config["policy"]["actions"] = {
            "main": {"tool_name": "response", "tool_args": {"text": "wrong"}},
            "finish": {"tool_name": "response", "tool_args": {"text": "wrong"}},
            "specialist_tool": {"tool_name": "response", "tool_args": {"text": "wrong"}},
            "safe": {"tool_name": "memory_load", "tool_args": {"query": "safe"}}}
        self.assertEqual(list(self.runtime.allowed_actions(self.config["policy"])), ["safe"])

    def test_intervention_during_decision_prevents_stale_tool(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "memory_load", "tool_args": {"query": "old"}}}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        agent.last_user_message = types.SimpleNamespace(output_text=lambda: "Old request")
        async def decide(state, choices):
            agent.last_user_message = types.SimpleNamespace(output_text=lambda: "New request")
            return types.SimpleNamespace(choice="lookup", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertFalse(self.runtime.should_decide(agent))

    def test_main_correction_runs_while_independent_host_actions_continue(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "first": {"tool_name": "memory_load", "tool_args": {"query": "first"},
                      "independent_while_main": True, "share_result_with_backend": True},
            "second": {"tool_name": "memory_load", "tool_args": {"query": "second"},
                       "independent_while_main": True, "share_result_with_backend": True},
            "dependent": {"tool_name": "memory_load", "tool_args": {"query": "dependent"}},
        }
        states = []
        choices_seen = []
        correction_started = asyncio.Event()
        release_correction = asyncio.Event()

        async def correction(agent, decision_state, timeout):
            correction_started.set()
            await release_correction.wait()
            return {"kind": "correction", "text": "Prefer the verified project memory."}

        async def decide(state, choices):
            states.append(state)
            choices_seen.append(set(choices))
            order = len(states)
            selected = {1: "main", 2: "first", 3: "second", 4: "dependent"}[order]
            return types.SimpleNamespace(choice=selected, confidence=0.99, backend="jev")

        self.runtime._run_main_correction = correction
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)

        async def scenario():
            first = await self.runtime.main_decision(agent)
            await correction_started.wait()
            self.assertEqual(json.loads(first)["tool_args"]["query"], "first")
            self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "First result"))
            agent.loop_data.iteration = 1
            second = await self.runtime.main_decision(agent)
            self.assertEqual(json.loads(second)["tool_args"]["query"], "second")
            self.assertNotIn("dependent", choices_seen[2])
            self.assertNotIn("finish", choices_seen[2])
            release_correction.set()
            await asyncio.sleep(0)
            self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "Second result"))
            agent.loop_data.iteration = 2
            third = await self.runtime.main_decision(agent)
            self.assertEqual(json.loads(third)["tool_args"]["query"], "dependent")
            self.assertIn("dependent", choices_seen[3])
            self.assertIn("verified project memory", states[3])
            self.assertIn("Inspect this page", states[3])

        asyncio.run(scenario())

    def test_finished_main_does_not_override_independent_jev_action(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "independent": {"tool_name": "memory_load", "tool_args": {"query": "independent"},
                            "independent_while_main": True,
                            "share_result_with_backend": True},
            "dependent": {"tool_name": "memory_load", "tool_args": {"query": "dependent"}},
        }
        states = []
        correction_release = asyncio.Event()
        second_choice_entered = asyncio.Event()
        second_choice_release = asyncio.Event()

        async def correction(agent, decision_state, timeout):
            await correction_release.wait()
            return {"kind": "correction", "text": "Use the verified next step."}

        async def decide(state, choices):
            states.append(state)
            if len(states) == 2:
                second_choice_entered.set()
                await second_choice_release.wait()
            selected = {1: "main", 2: "independent", 3: "dependent"}[len(states)]
            return types.SimpleNamespace(choice=selected, confidence=0.99, backend="jev")

        self.runtime._run_main_correction = correction
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)

        async def scenario():
            first_task = asyncio.create_task(self.runtime.main_decision(agent))
            await second_choice_entered.wait()
            correction_release.set()
            pending = getattr(agent, self.runtime._TURN_STATE)["main_task"]
            self.assertIsNotNone(await pending)
            second_choice_release.set()
            first = await first_task
            self.assertEqual(json.loads(first)["tool_args"]["query"], "independent")
            self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "Observed fact"))
            agent.loop_data.iteration = 1
            second = await self.runtime.main_decision(agent)
            self.assertEqual(json.loads(second)["tool_args"]["query"], "dependent")
            self.assertIn("verified next step", states[2])

        asyncio.run(scenario())

    def test_no_independent_action_uses_normal_main_without_background_call(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "dependent": {"tool_name": "memory_load", "tool_args": {"query": "dependent"}}}
        async def decide(state, choices):
            return types.SimpleNamespace(choice="main", confidence=0.99, backend="jev")
        async def correction(agent, state, timeout):
            self.fail("Advisory Main must not run without independent work")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime._run_main_correction = correction
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))

    def test_end_turn_cancels_only_owned_advisory_task(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "first": {"tool_name": "memory_load", "tool_args": {"query": "first"},
                      "independent_while_main": True}}
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def correction(agent, state, timeout):
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        calls = 0
        async def decide(state, choices):
            nonlocal calls
            calls += 1
            return types.SimpleNamespace(choice="main" if calls == 1 else "first",
                                         confidence=0.99, backend="jev")
        self.runtime._run_main_correction = correction
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        async def scenario():
            self.assertIsNotNone(await self.runtime.main_decision(agent))
            await started.wait()
            self.runtime.end_turn(agent)
            self.runtime.end_turn(agent)
            await asyncio.sleep(0)
            self.assertTrue(cancelled.is_set())
            self.assertFalse(self.runtime.should_decide(agent))
        asyncio.run(scenario())

    def test_tool_availability_rechecked_before_dispatch(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "lookup": {"tool_name": "memory_load", "tool_args": {"query": "safe"}}}
        available = True
        self.runtime.is_tool_available = lambda agent, name: available
        async def decide(state, choices):
            nonlocal available
            available = False
            return types.SimpleNamespace(choice="lookup", confidence=0.99, backend="jev")
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))

    def test_exhausted_independent_choices_wait_for_existing_main(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "only": {"tool_name": "memory_load", "tool_args": {"query": "only"},
                     "independent_while_main": True}}
        started = asyncio.Event()
        release = asyncio.Event()
        cancelled = False
        async def correction(agent, state, timeout):
            nonlocal cancelled
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled = True
                raise
            return {"kind": "correction", "text": "No more independent work"}
        calls = 0
        async def decide(state, choices):
            nonlocal calls
            calls += 1
            return types.SimpleNamespace(choice="main" if calls == 1 else "only",
                                         confidence=0.99, backend="jev")
        self.runtime._run_main_correction = correction
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        async def scenario():
            self.assertIsNotNone(await self.runtime.main_decision(agent))
            await started.wait()
            self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "done"))
            agent.loop_data.iteration = 1
            next_call = asyncio.create_task(self.runtime.main_decision(agent))
            await asyncio.sleep(0)
            self.assertFalse(next_call.done())
            self.assertFalse(cancelled)
            release.set()
            self.assertIsNone(await next_call)
            self.assertFalse(cancelled)
        asyncio.run(scenario())

    def test_background_main_correction_uses_text_only_host_call(self):
        messages = types.ModuleType("langchain_core.messages")
        messages.SystemMessage = lambda content: ("system", content)
        messages.HumanMessage = lambda content: ("human", content)
        parent = types.ModuleType("langchain_core")
        seen = []
        class BackgroundAgent:
            async def call_chat_model(self, **kwargs):
                seen.append(kwargs)
                return ('{"kind":"correction","text":"Check the next result"}', "")
        with patch.dict(sys.modules, {"langchain_core": parent, "langchain_core.messages": messages}):
            result = asyncio.run(self.runtime._run_main_correction(
                BackgroundAgent(), "Uncertain subtask", 1))
        self.assertEqual(result, {"kind": "correction", "text": "Check the next result"})
        self.assertTrue(seen[0]["background"])
        self.assertFalse(seen[0]["explicit_caching"])
        self.assertEqual(seen[0]["messages"][1], ("human", "Uncertain subtask"))

    def test_main_correction_timeout_does_not_wait_for_uncancellable_model(self):
        messages = types.ModuleType("langchain_core.messages")
        messages.SystemMessage = lambda content: ("system", content)
        messages.HumanMessage = lambda content: ("human", content)
        parent = types.ModuleType("langchain_core")
        class SlowAgent:
            def __init__(self):
                self.release = asyncio.Event()
                self.cancel_seen = False
                self.calls = 0

            async def call_chat_model(self, **kwargs):
                self.calls += 1
                if self.calls > 1:
                    return ('{"kind":"correction","text":"fresh"}', "")
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.cancel_seen = True
                    await self.release.wait()
                    return ('{"kind":"correction","text":"stale"}', "")

        async def scenario():
            agent = SlowAgent()
            with patch.dict(sys.modules, {"langchain_core": parent,
                                          "langchain_core.messages": messages}):
                result = await asyncio.wait_for(
                    self.runtime._run_main_correction(agent, "Uncertain", 0.01), 0.2)
                self.assertIsNone(result)
                await asyncio.sleep(0)
                self.assertTrue(agent.cancel_seen)
                self.assertIsNone(await self.runtime._run_main_correction(
                    agent, "Another uncertain subtask", 0.01))
                self.assertEqual(agent.calls, 1)
                agent.release.set()
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                self.assertEqual(await self.runtime._run_main_correction(
                    agent, "New uncertain subtask", 0.1),
                    {"kind": "correction", "text": "fresh"})
                self.assertEqual(agent.calls, 2)

        asyncio.run(scenario())

    def test_disable_while_waiting_cannot_commit_stale_main_final(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "only": {"tool_name": "memory_load", "tool_args": {"query": "only"},
                     "independent_while_main": True}}
        release = asyncio.Event()
        async def correction(agent, state, timeout):
            await release.wait()
            return {"kind": "final", "text": "Stale final"}
        calls = 0
        async def decide(state, choices):
            nonlocal calls
            calls += 1
            return types.SimpleNamespace(choice="main" if calls == 1 else "only",
                                         confidence=0.99, backend="jev")
        self.runtime._run_main_correction = correction
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        async def scenario():
            self.assertIsNotNone(await self.runtime.main_decision(agent))
            self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "result"))
            agent.loop_data.iteration = 1
            pending = asyncio.create_task(self.runtime.main_decision(agent))
            await asyncio.sleep(0)
            self.config["main"]["enabled"] = False
            release.set()
            self.assertIsNone(await pending)
            self.assertNotIn("Main supplied final response", [event[0][1] for event in self.timeline_events])
        asyncio.run(scenario())

    def test_changed_policy_discards_pending_main_correction(self):
        self.config["policy"]["action_precedence"] = "main_first"
        independent = {"tool_name": "memory_load", "tool_args": {"query": "safe"},
                       "independent_while_main": True}
        self.config["policy"]["actions"] = {"independent": independent}
        release = asyncio.Event()
        entered = asyncio.Event()
        async def correction(agent, state, timeout):
            entered.set()
            await release.wait()
            return {"kind": "correction", "text": "Outdated guidance"}
        calls = 0
        async def decide(state, choices):
            nonlocal calls
            calls += 1
            return types.SimpleNamespace(choice="main" if calls == 1 else "wait_main",
                                         confidence=0.99, backend="jev")
        self.runtime._run_main_correction = correction
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        async def scenario():
            pending = asyncio.create_task(self.runtime.main_decision(agent))
            await entered.wait()
            independent["description"] = "Changed during Main reasoning"
            release.set()
            self.assertIsNone(await pending)
            self.assertFalse(getattr(agent, self.runtime._TURN_STATE)["main_guidance"])
        asyncio.run(scenario())

    def test_failed_advisory_does_not_unblock_dependent_action(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "independent": {"tool_name": "memory_load", "tool_args": {"query": "safe"},
                            "independent_while_main": True},
            "dependent": {"tool_name": "memory_load", "tool_args": {"query": "uncertain"}},
        }
        calls = 0
        async def decide(state, choices):
            nonlocal calls
            calls += 1
            return types.SimpleNamespace(choice="main" if calls == 1 else "independent",
                                         confidence=0.99, backend="jev")
        async def correction(agent, state, timeout):
            return None
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime._run_main_correction = correction
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        async def scenario():
            self.assertIsNotNone(await self.runtime.main_decision(agent))
            await asyncio.sleep(0)
            self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "result"))
            agent.loop_data.iteration = 1
            self.assertIsNone(await self.runtime.main_decision(agent))
            self.assertEqual(calls, 2)
        asyncio.run(scenario())

    def test_corrected_action_mutation_during_decision_cannot_dispatch(self):
        self.config["policy"]["action_precedence"] = "main_first"
        dependent = {"tool_name": "memory_load", "tool_args": {"query": "safe"}}
        self.config["policy"]["actions"] = {
            "independent": {"tool_name": "memory_load", "tool_args": {"query": "other"},
                            "independent_while_main": True},
            "dependent": dependent,
        }
        calls = 0
        async def decide(state, choices):
            nonlocal calls
            calls += 1
            if calls == 3:
                dependent["tool_args"]["query"] = "changed"
            return types.SimpleNamespace(choice={1: "main", 2: "wait_main", 3: "dependent"}[calls],
                                         confidence=0.99, backend="jev")
        async def correction(agent, state, timeout):
            return {"kind": "correction", "text": "The dependent action is now safe."}
        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime._run_main_correction = correction
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))
        self.assertEqual(calls, 3)

    def test_main_model_change_during_corrected_choice_cannot_dispatch(self):
        self.config["policy"]["action_precedence"] = "main_first"
        self.config["policy"]["actions"] = {
            "independent": {"tool_name": "memory_load", "tool_args": {"query": "safe"},
                            "independent_while_main": True},
            "dependent": {"tool_name": "memory_load", "tool_args": {"query": "after advice"}},
        }
        calls = 0

        async def decide(state, choices):
            nonlocal calls
            calls += 1
            if calls == 3:
                self.config["main"]["model"] = "replacement-model"
            return types.SimpleNamespace(choice={1: "main", 2: "wait_main", 3: "dependent"}[calls],
                                         confidence=0.99, backend="jev")

        async def correction(agent, state, timeout):
            return {"kind": "correction", "text": "The dependent action is now safe."}

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime._run_main_correction = correction
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(Agent())))
        self.assertEqual(calls, 3)
        self.assertEqual(self.timeline_events[-1][1]["detail"], "Main correction became stale")

    def test_main_proposal_rechecks_current_action_and_records_ownership(self):
        """Main may select only a still-configured host action, never arguments."""
        chosen = {"tool_name": "memory_load", "tool_args": {"query": "verified"}}
        self.config["policy"]["actions"] = {"chosen": chosen}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["main_proposal"] = {"kind": "action", "action_id": "chosen"}
        state["main_offered_actions"] = {"chosen": dict(chosen)}

        action = self.runtime._main_proposal_action(
            agent, state, self.config["policy"], "Inspect this page")

        self.assertEqual(json.loads(action), chosen)
        self.assertEqual(state["owner"], "main")
        self.assertEqual(state["used_action_ids"], {"chosen"})
        self.assertEqual(state["pending"]["action_id"], "chosen")
        self.assertTrue(any(event[0][1] == "main_action" for event in self.timeline_events))

    def test_stale_main_proposal_cannot_dispatch_or_replay_a_changed_action(self):
        chosen = {"tool_name": "memory_load", "tool_args": {"query": "before"}}
        self.config["policy"]["actions"] = {"chosen": chosen}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["main_proposal"] = {"kind": "action", "action_id": "chosen"}
        state["main_offered_actions"] = {"chosen": dict(chosen)}
        self.config["policy"]["actions"]["chosen"] = {
            "tool_name": "memory_load", "tool_args": {"query": "after"}}

        self.assertIsNone(self.runtime._main_proposal_action(
            agent, state, self.config["policy"], "Inspect this page"))
        self.assertTrue(state["main_stale"])
        self.assertEqual(state["used_action_ids"], set())
        self.assertIsNone(state["pending"])

    def test_host_main_delegation_accepts_only_current_unique_eligible_ids(self):
        first = {"tool_name": "memory_load", "tool_args": {"query": "first"}}
        second = {"tool_name": "memory_load", "tool_args": {"query": "second"}}
        self.config["policy"]["actions"] = {"first": first, "second": second}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})

        self.assertFalse(self.runtime.record_main_delegation(agent, ["first", "first"]))
        self.assertFalse(self.runtime.record_main_delegation(agent, ["missing"]))
        self.assertTrue(self.runtime.record_main_delegation(agent, ["second"]))
        self.assertEqual(state["main_delegate_ids"], frozenset({"second"}))
        self.assertTrue(state["delegate_pending"])
        self.assertEqual(state["owner"], "system_1")
        self.assertTrue(any(event[0][1] == "main_delegate" for event in self.timeline_events))

    def test_main_delegation_limits_the_next_system1_choice_to_its_current_subset(self):
        selected = {"tool_name": "memory_load", "tool_args": {"query": "selected"}}
        excluded = {"tool_name": "memory_load", "tool_args": {"query": "excluded"}}
        self.config["policy"]["actions"] = {"selected": selected, "excluded": excluded}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})
        self.assertTrue(self.runtime.record_main_delegation(agent, ["selected"]))
        agent.loop_data.iteration = 1
        offered = []

        async def decide(_state, choices):
            offered.append(set(choices))
            return types.SimpleNamespace(choice="selected", confidence=0.99, backend="jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)
        action = asyncio.run(self.runtime.main_decision(agent))

        self.assertEqual(json.loads(action), selected)
        self.assertEqual(offered, [{"main", "selected"}])
        self.assertEqual(state["used_action_ids"], {"selected"})

    def test_delegated_decider_receives_prior_evidence_and_explicit_main_context(self):
        skills = {"tool_name": "skills_tool", "tool_args": {"action": "search", "query": "system_1"},
                  "share_result_with_backend": True}
        pr_status = {"tool_name": "github_mcp_server.get_pull_request_status",
                     "tool_args": {"owner": "Omni-NexusAI", "repo": "agent-plugins", "pull_number": 11}}
        self.config["policy"]["actions"] = {"skills_check": skills, "pr_status": pr_status}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main", "used_action_ids": {"skills_check"},
                      "actions_submitted": 1})
        state["observations"].append({
            "action_id": "skills_check", "action_definition": dict(skills),
            "tool_name": "skills_tool", "result": "skills evidence", "return_result": "",
            "binding_result": "", "truncated": False,
        })
        self.assertTrue(self.runtime.record_main_delegation(agent, ["pr_status"]))
        agent.loop_data.iteration = 1
        calls = []

        async def decide(decision_state, choices):
            calls.append((decision_state, dict(choices)))
            return types.SimpleNamespace(choice="pr_status", confidence=0.99, backend="jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, choices, threshold: choices.get(result.choice)
        action = asyncio.run(self.runtime.main_decision(agent))

        self.assertEqual(json.loads(action), pr_status)
        self.assertEqual(set(calls[0][1]), {"main", "pr_status"})
        self.assertEqual(list(calls[0][1]), ["pr_status", "main"])
        self.assertIn("Original request: Inspect this page", calls[0][0])
        self.assertIn("Prior choice: skills_check", calls[0][0])
        self.assertIn("Observed result: skills evidence", calls[0][0])
        self.assertIn("Main delegation:", calls[0][0])
        self.assertIn("pr_status", calls[0][0])
        self.assertTrue(calls[0][0].startswith("Main delegation:"))

    def test_main_can_decline_a_delegated_choice_without_a_host_dispatch(self):
        selected = {"tool_name": "memory_load", "tool_args": {"query": "delegated"}}
        self.config["policy"]["actions"] = {"selected": selected}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})
        self.assertTrue(self.runtime.record_main_delegation(agent, ["selected"]))
        agent.loop_data.iteration = 1

        async def decide(_state, choices):
            self.assertIn("main", choices)
            return types.SimpleNamespace(choice="main", confidence=0.99, backend="jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(state["complete"])
        self.assertEqual(state["owner"], "main")
        self.assertEqual(state["used_action_ids"], set())
        self.assertIsNone(state["pending"])
        self.assertEqual(self.timeline_events[-1][1]["detail"],
                         "System 1 declined Main delegation")
        note = self.runtime.main_handoff_note(agent)
        self.assertIn("did not submit or execute a System 1 action", note)
        self.assertIn("ordinary Agent Zero tool", note)
        self.assertIn("report that it is unavailable", note)
        self.assertIn("Do not claim the delegated action ran", note)

    def test_repeated_identical_main_delegation_requires_fresh_evidence(self):
        selected = {"tool_name": "memory_load", "tool_args": {"query": "delegated"}}
        self.config["policy"]["actions"] = {"selected": selected}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})

        self.assertTrue(self.runtime.record_main_delegation(agent, ["selected"]))
        state.update({"complete": True, "owner": "main", "delegate_pending": False,
                      "observation": None})
        self.assertFalse(self.runtime.record_main_delegation(agent, ["selected"]))

    def test_fresh_host_evidence_allows_a_new_identical_main_delegation(self):
        selected = {"tool_name": "github_mcp_server.get_pull_request_status",
                    "tool_args": {"owner": "Omni-NexusAI", "repo": "agent-plugins", "pull_number": 11}}
        self.config["policy"]["actions"] = {"selected": selected}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})

        self.assertTrue(self.runtime.record_main_delegation(agent, ["selected"]))
        state.update({"complete": True, "owner": "main", "delegate_pending": False,
                      "observation": None})
        self.assertTrue(self.runtime.record_main_host_action(
            agent, "memory_load", {"query": "fresh host observation"}))
        self.assertTrue(self.runtime.record_main_delegation(agent, ["selected"]))

    def test_low_confidence_delegated_choice_returns_to_main_without_dispatch(self):
        selected = {"tool_name": "memory_load", "tool_args": {"query": "delegated"}}
        self.config["policy"].update({"min_choice_probability": 0.9,
                                       "actions": {"selected": selected}})
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})
        self.assertTrue(self.runtime.record_main_delegation(agent, ["selected"]))
        agent.loop_data.iteration = 1

        async def decide(_state, _choices):
            return types.SimpleNamespace(choice="selected", confidence=0.89, backend="jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertTrue(state["complete"])
        self.assertEqual(state["owner"], "main")
        self.assertEqual(state["used_action_ids"], set())
        self.assertIsNone(state["pending"])

    def test_oversized_delegated_decider_state_hands_back_without_partial_context(self):
        selected = {"tool_name": "memory_load", "tool_args": {"query": "delegated"},
                    "share_result_with_backend": True}
        self.config["policy"].update({"max_state_chars": 256, "actions": {"selected": selected}})
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})
        state["observations"].append({
            "action_id": "selected", "action_definition": dict(selected),
            "tool_name": "memory_load", "result": "evidence " * 200,
            "return_result": "", "binding_result": "", "truncated": False,
        })
        # A distinct still-eligible action is delegated; the large prior result
        # must make the complete bounded state fail closed before Jev is called.
        other = {"tool_name": "memory_load", "tool_args": {"query": "other"}}
        self.config["policy"]["actions"]["other"] = other
        self.assertTrue(self.runtime.record_main_delegation(agent, ["other"]))
        agent.loop_data.iteration = 1
        calls = []

        async def decide(*args):
            calls.append(args)
            raise AssertionError("oversized delegated state reached Jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertEqual(calls, [])
        self.assertTrue(state["complete"])
        self.assertEqual(state["owner"], "main")
        self.assertIsNone(state["pending"])

    def test_unavailable_host_tool_cannot_be_delegated_or_dispatched(self):
        denied = {"tool_name": "github_mcp_server.get_pull_request_status",
                  "tool_args": {"owner": "Omni-NexusAI", "repo": "agent-plugins", "pull_number": 11}}
        self.config["policy"]["actions"] = {"denied": denied}
        self.runtime.is_tool_available = lambda agent, name: False
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})

        self.assertFalse(self.runtime.record_main_delegation(agent, ["denied"]))
        state.update({"complete": False, "owner": "system_1", "observation": {"delegation": True},
                      "delegate_pending": True})
        agent.loop_data.iteration = 1
        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertIsNone(state["pending"])
        self.assertNotIn("denied", state["used_action_ids"])

    def test_main_cannot_delegate_a_call_already_executed_by_system1(self):
        repeated = {"tool_name": "memory_load", "tool_args": {"query": "already ran"}}
        self.config["policy"]["actions"] = {"repeated": repeated}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main", "used_action_ids": {"repeated"}})

        self.assertFalse(self.runtime.record_main_delegation(agent, ["repeated"]))
        self.assertFalse(state["delegate_pending"])
        self.assertIsNone(state["main_delegate_ids"])

    def test_main_host_action_record_prevents_a_later_delegated_replay(self):
        call = {"tool_name": "memory_load", "tool_args": {"query": "already ran"}}
        self.config["policy"]["actions"] = {"repeated": dict(call)}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})

        self.assertTrue(self.runtime.record_main_host_action(
            agent, call["tool_name"], call["tool_args"]))
        self.assertFalse(self.runtime.record_main_delegation(agent, ["repeated"]))
        self.assertFalse(self.runtime.record_main_host_action(
            agent, call["tool_name"], call["tool_args"], succeeded=False))

    def test_main_action_result_stays_with_main_until_explicit_later_delegation(self):
        main_action = {"tool_name": "memory_load", "tool_args": {"query": "main action"}}
        follow_up = {"tool_name": "memory_load", "tool_args": {"query": "follow up"}}
        self.config["policy"]["actions"] = {"main_action": main_action, "follow_up": follow_up}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=0)
        state = self.runtime._turn_state(agent, create=True)
        state.update({
            "owner": "main",
            "used_action_ids": {"main_action"},
            "pending": {
                "action_id": "main_action", "tool_name": "memory_load",
                "action_definition": dict(main_action), "share_result": False,
                "bind_result": False, "return_result": False, "result_limit": 2000,
            },
        })

        self.assertTrue(self.runtime.record_host_result(agent, "memory_load", "main result"))
        self.assertTrue(state["complete"])
        self.assertFalse(self.runtime.should_decide(agent))

        self.assertTrue(self.runtime.record_main_delegation(agent, ["follow_up"]))
        agent.loop_data.iteration = 1
        self.assertTrue(self.runtime.should_decide(agent))

    def test_parallel_start_is_not_recorded_as_a_completed_main_call(self):
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)

        self.assertFalse(self.runtime.record_main_host_action(
            agent, "parallel", {"tool_calls": []}, succeeded=True))
        self.assertEqual(state.get("call_signatures", set()), set())

    def test_main_owned_parallel_pending_children_block_duplicate_system1_handback(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"}}
        bravo = {"tool_name": "memory_load", "tool_args": {"query": "bravo"}}
        self.config["policy"]["actions"] = {
            "alpha": alpha, "bravo": bravo,
            "replay_alpha": dict(alpha), "replay_bravo": dict(bravo),
        }
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(
            iteration=0,
            current_tool=types.SimpleNamespace(name="parallel", args={"tool_calls": [
                {"tool_name": "memory_load", "tool_args": {"query": "alpha"}},
                {"tool_name": "memory_load", "tool_args": {"query": "bravo"}},
            ], "wait": False}),
        )
        state = self.runtime._turn_state(agent, create=True)
        state.update({"owner": "main", "actions_submitted": 2,
                      "used_action_ids": {"alpha", "bravo"},
                      "pending": {"tool_name": "parallel", "wait": False, "job_ids": [], "batch": [
                          {"action_id": "alpha", "tool_name": "memory_load",
                           "action_definition": alpha, "share_result": False, "bind_result": False,
                           "return_result": False, "result_limit": 2000},
                          {"action_id": "bravo", "tool_name": "memory_load",
                           "action_definition": bravo, "share_result": False, "bind_result": False,
                           "return_result": False, "result_limit": 2000},
                      ]}})
        started = json.dumps({"status": "started", "jobs": [
            {"job_id": "alpha-job", "tool_name": "memory_load", "state": "running"},
            {"job_id": "bravo-job", "tool_name": "memory_load", "state": "pending"},
        ]})

        self.assertFalse(self.runtime.record_host_result(agent, "parallel", started))
        self.assertTrue(state["complete"])
        self.assertEqual(state["owner"], "main")
        self.assertFalse(self.runtime.record_main_delegation(agent, ["replay_alpha"]))
        self.assertFalse(self.runtime.record_main_delegation(agent, ["replay_bravo"]))

    def test_malformed_initial_main_parallel_mapping_keeps_every_child_unresolved(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"}}
        bravo = {"tool_name": "memory_load", "tool_args": {"query": "bravo"}}
        self.config["policy"]["actions"] = {
            "replay_alpha": dict(alpha), "replay_bravo": dict(bravo)}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(
            iteration=0,
            current_tool=types.SimpleNamespace(name="parallel", args={"tool_calls": [
                {"tool_name": "memory_load", "tool_args": {"query": "alpha"}},
                {"tool_name": "memory_load", "tool_args": {"query": "bravo"}},
            ], "wait": False}),
        )
        state = self.runtime._turn_state(agent, create=True)
        state.update({"complete": True, "owner": "main"})
        malformed = json.dumps({"status": "started", "jobs": [
            {"job_id": "alpha-job", "tool_name": "memory_load", "state": "running"},
        ]})

        self.assertFalse(self.runtime.record_host_result(agent, "parallel", malformed))
        self.assertFalse(self.runtime.record_main_delegation(agent, ["replay_alpha"]))
        self.assertFalse(self.runtime.record_main_delegation(agent, ["replay_bravo"]))
        self.assertNotIn("alpha-job", repr(state))

    def test_main_parallel_success_blocks_replay_but_failed_child_allows_safe_retry(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"}}
        bravo = {"tool_name": "memory_load", "tool_args": {"query": "bravo"}}
        self.config["policy"]["actions"] = {
            "alpha": alpha, "bravo": bravo,
            "replay_alpha": dict(alpha), "retry_bravo": dict(bravo),
        }
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(
            iteration=0,
            current_tool=types.SimpleNamespace(name="parallel", args={"tool_calls": [
                {"tool_name": "memory_load", "tool_args": {"query": "alpha"}},
                {"tool_name": "memory_load", "tool_args": {"query": "bravo"}},
            ], "wait": False}),
        )
        state = self.runtime._turn_state(agent, create=True)
        state.update({"owner": "main", "actions_submitted": 2,
                      "used_action_ids": {"alpha", "bravo"},
                      "pending": {"tool_name": "parallel", "wait": False,
                                  "job_ids": [], "batch": [
                          {"action_id": "alpha", "tool_name": "memory_load",
                           "action_definition": alpha, "share_result": False, "bind_result": False,
                           "return_result": False, "result_limit": 2000},
                          {"action_id": "bravo", "tool_name": "memory_load",
                           "action_definition": bravo, "share_result": False, "bind_result": False,
                           "return_result": False, "result_limit": 2000},
                      ]}})
        started = json.dumps({"status": "started", "jobs": [
            {"job_id": "alpha-job", "tool_name": "memory_load", "state": "running"},
            {"job_id": "bravo-job", "tool_name": "memory_load", "state": "pending"},
        ]})
        mixed = json.dumps({"status": "partial", "jobs": [
            {"job_id": "main-job", "tool_name": "code_execution_tool", "state": "success",
             "result": "Main-only content"},
            {"job_id": "bravo-job", "tool_name": "memory_load", "state": "error",
             "error": "denied"},
            {"job_id": "alpha-job", "tool_name": "memory_load", "state": "success",
             "result": "alpha result"},
        ]})

        self.assertFalse(self.runtime.record_host_result(agent, "parallel", started))
        agent.loop_data.current_tool.args = {"action": "await",
                                              "job_ids": ["alpha-job", "bravo-job"]}
        self.assertTrue(self.runtime.record_host_result(agent, "parallel", mixed))
        self.assertIsNone(state["pending"])
        self.assertTrue(state["complete"])
        self.assertEqual(state["owner"], "main")
        self.assertNotIn("Main-only content", repr(state))
        self.assertFalse(self.runtime.record_main_delegation(agent, ["replay_alpha"]))
        self.assertTrue(self.runtime.record_main_delegation(agent, ["retry_bravo"]))

    def test_distinct_action_ids_cannot_replay_the_same_host_call(self):
        call = {"tool_name": "memory_load", "tool_args": {"query": "same call"}}
        self.config["policy"]["actions"] = {"first": dict(call), "second": dict(call)}
        agent = Agent()
        agent.loop_data = types.SimpleNamespace(iteration=1)
        state = self.runtime._turn_state(agent, create=True)
        state["used_action_ids"].add("first")
        state["observation"] = {"action_id": "first", "tool_name": "memory_load",
                                "action_definition": dict(call), "result": "",
                                "return_result": "", "binding_result": "", "truncated": False}

        async def decide(_state, _choices):
            return types.SimpleNamespace(choice="second", confidence=0.99, backend="jev")

        self.runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=decide)
        self.runtime.selected_action = lambda result, actions, threshold: actions.get(result.choice)

        self.assertIsNone(asyncio.run(self.runtime.main_decision(agent)))
        self.assertEqual(state["used_action_ids"], {"first"})
        self.assertIsNone(state["pending"])

    def test_parallel_batch_requires_both_safety_opt_ins_and_uses_native_shape(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"},
                 "independent_while_main": True, "parallel_safe": True}
        bravo = {"tool_name": "memory_load", "tool_args": {"query": "bravo"},
                 "independent_while_main": True, "parallel_safe": True}
        dependent = {"tool_name": "memory_load", "tool_args": {"query": "dependent"}}
        self.config["policy"]["actions"] = {
            "alpha": alpha, "bravo": bravo, "dependent": dependent}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["main_requested"] = True
        chosen = []

        async def decide(_state, choices):
            chosen.append(set(choices))
            return types.SimpleNamespace(choice="bravo", confidence=0.99, backend="jev")

        client = types.SimpleNamespace(choose=decide)
        batch = asyncio.run(self.runtime._maybe_batch_independent(
            agent, state, client, "Inspect this page", self.config["policy"]["actions"],
            "alpha", self.config["policy"], "Inspect this page", 0.85))

        self.assertEqual(json.loads(batch), {
            "tool_name": "parallel",
            "tool_args": {"tool_calls": [
                {"tool_name": "memory_load", "tool_args": {"query": "alpha"}},
                {"tool_name": "memory_load", "tool_args": {"query": "bravo"}},
            ], "wait": False},
        })
        self.assertEqual(chosen, [{"batch_stop", "bravo"}])
        self.assertEqual(state["used_action_ids"], {"alpha", "bravo"})
        self.assertNotIn("dependent", state["used_action_ids"])
        self.assertEqual(state["pending"]["tool_name"], "parallel")
        self.assertFalse(state["pending"]["wait"])
        self.assertEqual(state["owner"], "main")
        self.assertTrue(any(event[0][1] == "parallel_started" for event in self.timeline_events))

    def test_parallel_wait_policy_requires_terminal_job_results_before_next_s1_decision(self):
        actions = {
            key: {"tool_name": "memory_load", "tool_args": {"query": key},
                  "independent_while_main": True, "parallel_safe": True}
            for key in ("alpha", "bravo")
        }
        self.config["policy"].update({"actions": actions, "parallel_wait_for_results": True})
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["main_requested"] = True

        async def decide(_state, _choices):
            return types.SimpleNamespace(choice="bravo", confidence=0.99, backend="jev")

        batch = asyncio.run(self.runtime._maybe_batch_independent(
            agent, state, types.SimpleNamespace(choose=decide), "Inspect this page", actions,
            "alpha", self.config["policy"], "Inspect this page", 0.85))

        self.assertTrue(json.loads(batch)["tool_args"]["wait"])
        self.assertTrue(state["pending"]["wait"])
        self.assertEqual(state["owner"], "system_1")

    def test_independent_batch_can_run_before_main_is_requested(self):
        actions = {key: {"tool_name": "memory_load", "tool_args": {"query": key},
                         "independent_while_main": True, "parallel_safe": True}
                   for key in ("alpha", "bravo")}
        self.config["policy"]["actions"] = actions
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)

        async def decide(_state, _choices):
            return types.SimpleNamespace(choice="bravo", confidence=0.99, backend="jev")

        batch = asyncio.run(self.runtime._maybe_batch_independent(
            agent, state, types.SimpleNamespace(choose=decide), "Inspect this page", actions,
            "alpha", self.config["policy"], "Inspect this page", 0.85))

        self.assertTrue(json.loads(batch)["tool_args"]["wait"])
        self.assertEqual(state["owner"], "system_1")
        self.assertEqual(state["used_action_ids"], {"alpha", "bravo"})

    def test_parallel_batch_rechecks_a_threshold_changed_while_selecting_children(self):
        actions = {
            key: {"tool_name": "memory_load", "tool_args": {"query": key},
                  "independent_while_main": True, "parallel_safe": True}
            for key in ("alpha", "bravo")
        }
        self.config["policy"].update({"actions": actions, "min_choice_probability": 0.85})
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["main_requested"] = True

        async def decide(_state, _choices):
            self.config["policy"]["min_choice_probability"] = 0.95
            return types.SimpleNamespace(choice="bravo", confidence=0.90, backend="jev")

        batch = asyncio.run(self.runtime._maybe_batch_independent(
            agent, state, types.SimpleNamespace(choose=decide), "Inspect this page", actions,
            "alpha", self.config["policy"], "Inspect this page", 0.85))

        self.assertIsNone(batch)
        self.assertEqual(state["used_action_ids"], set())
        self.assertIsNone(state["pending"])

    def test_parallel_started_jobs_are_not_evidence_until_matching_terminal_results_arrive(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"},
                 "share_result_with_backend": True, "allow_result_bindings": True}
        bravo = {"tool_name": "memory_load", "tool_args": {"query": "bravo"},
                 "share_result_with_backend": True, "allow_result_bindings": True}
        self.config["policy"]["actions"] = {"alpha": alpha, "bravo": bravo}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["pending"] = {"tool_name": "parallel", "wait": False, "job_ids": [], "batch": [
            {"action_id": "alpha", "tool_name": "memory_load", "action_definition": alpha,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
            {"action_id": "bravo", "tool_name": "memory_load", "action_definition": bravo,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
        ]}
        started = json.dumps({"status": "started", "jobs": [
            {"job_id": "alpha-job", "tool_name": "memory_load", "state": "running"},
            {"job_id": "bravo-job", "tool_name": "memory_load", "state": "pending"},
        ]})
        completed = json.dumps({"status": "success", "jobs": [
            {"job_id": "alpha-job", "tool_name": "memory_load", "state": "success",
             "result": "alpha result"},
            {"job_id": "bravo-job", "tool_name": "memory_load", "state": "success",
             "result": "bravo result"},
        ]})

        self.assertFalse(self.runtime.record_host_result(agent, "parallel", started))
        self.assertEqual(state["observations"], [])
        self.assertEqual(state["pending"]["job_ids"], ["alpha-job", "bravo-job"])
        self.assertTrue(state["complete"])
        self.assertEqual(state["owner"], "main")
        self.assertEqual(self.runtime.pending_parallel_job_ids(agent), ["alpha-job", "bravo-job"])
        self.assertTrue(self.runtime.record_host_result(agent, "parallel", completed))
        self.assertEqual([item["action_id"] for item in state["observations"]], ["alpha", "bravo"])
        self.assertEqual([item["binding_result"] for item in state["observations"]],
                         ["alpha result", "bravo result"])
        self.assertIsNone(state["pending"])
        self.assertEqual(self.runtime.pending_parallel_job_ids(agent), [])

    def test_parallel_failure_or_interrupt_never_becomes_a_bindable_child_result(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"},
                 "share_result_with_backend": True, "allow_result_bindings": True}
        bravo = {"tool_name": "memory_load", "tool_args": {"query": "bravo"},
                 "share_result_with_backend": True, "allow_result_bindings": True}
        self.config["policy"]["actions"] = {"alpha": alpha, "bravo": bravo}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["pending"] = {"tool_name": "parallel", "wait": True,
                            "job_ids": ["alpha-job", "bravo-job"], "batch": [
            {"action_id": "alpha", "tool_name": "memory_load", "action_definition": alpha,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
            {"action_id": "bravo", "tool_name": "memory_load", "action_definition": bravo,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
        ]}
        partial = json.dumps({"status": "partial", "jobs": [
            {"job_id": "alpha-job", "tool_name": "memory_load", "state": "success",
             "result": "alpha result"},
            {"job_id": "bravo-job", "tool_name": "memory_load", "state": "cancelled",
             "error": "interrupted"},
        ]})

        self.assertTrue(self.runtime.record_host_result(agent, "parallel", partial))
        self.assertEqual(len(state["observations"]), 2)
        failed = state["observations"][1]
        self.assertEqual(failed["action_id"], "bravo")
        self.assertEqual(failed["binding_result"], "")
        self.assertEqual(failed["result"], "")
        self.assertIsNone(state["pending"])
        self.assertTrue(any(event[0][1] == "parallel_failed" for event in self.timeline_events))

    def test_parallel_await_subset_tracks_remaining_children_and_never_replays_a_result(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"},
                 "share_result_with_backend": True, "allow_result_bindings": True}
        bravo = {"tool_name": "memory_load", "tool_args": {"query": "bravo"},
                 "share_result_with_backend": True, "allow_result_bindings": True}
        self.config["policy"]["actions"] = {"alpha": alpha, "bravo": bravo}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["pending"] = {"tool_name": "parallel", "wait": True,
                            "job_ids": ["alpha-job", "bravo-job"], "batch": [
            {"action_id": "alpha", "tool_name": "memory_load", "action_definition": alpha,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
            {"action_id": "bravo", "tool_name": "memory_load", "action_definition": bravo,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
        ]}
        bravo_only = json.dumps({"status": "partial", "jobs": [
            {"job_id": "bravo-job", "tool_name": "memory_load", "state": "success",
             "result": "bravo result"},
        ]})
        alpha_only = json.dumps({"status": "success", "jobs": [
            {"job_id": "alpha-job", "tool_name": "memory_load", "state": "success",
             "result": "alpha result"},
        ]})

        self.assertTrue(self.runtime.record_host_result(agent, "parallel", bravo_only))
        self.assertEqual([item["action_id"] for item in state["observations"]], ["bravo"])
        self.assertIsNotNone(state["pending"])
        self.assertEqual(self.runtime.pending_parallel_job_ids(agent), ["alpha-job"])
        self.assertTrue(self.runtime.record_host_result(agent, "parallel", alpha_only))
        self.assertEqual([item["action_id"] for item in state["observations"]], ["bravo", "alpha"])
        self.assertIsNone(state["pending"])
        self.assertEqual(self.runtime.pending_parallel_job_ids(agent), [])
        self.assertFalse(self.runtime.record_host_result(agent, "parallel", bravo_only))

    def test_mixed_main_and_system1_parallel_await_records_only_tracked_children(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"},
                 "share_result_with_backend": True, "allow_result_bindings": True}
        self.config["policy"]["actions"] = {"alpha": alpha}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["pending"] = {"tool_name": "parallel", "wait": False,
                            "job_ids": ["system1-alpha"], "batch": [
            {"action_id": "alpha", "tool_name": "memory_load", "action_definition": alpha,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
        ]}
        aggregate = json.dumps({"status": "success", "jobs": [
            {"job_id": "main-job", "tool_name": "code_execution_tool", "state": "success",
             "result": "Main-owned result"},
            {"job_id": "system1-alpha", "tool_name": "memory_load", "state": "success",
             "result": "System 1 result"},
        ]})

        self.assertTrue(self.runtime.record_host_result(agent, "parallel", aggregate))
        self.assertEqual([item["action_id"] for item in state["observations"]], ["alpha"])
        self.assertEqual(state["observations"][0]["binding_result"], "System 1 result")
        self.assertIsNone(state["pending"])

    def test_oversized_parallel_result_recovers_known_terminal_jobs_but_keeps_running_ids(self):
        alpha = {"tool_name": "memory_load", "tool_args": {"query": "alpha"}}
        bravo = {"tool_name": "memory_load", "tool_args": {"query": "bravo"}}
        self.config["policy"]["actions"] = {"alpha": alpha, "bravo": bravo}
        agent = Agent()
        agent.context = object()
        state = self.runtime._turn_state(agent, create=True)
        state["pending"] = {"tool_name": "parallel", "wait": False,
                            "job_ids": ["alpha-job", "bravo-job"], "batch": [
            {"action_id": "alpha", "tool_name": "memory_load", "action_definition": alpha,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
            {"action_id": "bravo", "tool_name": "memory_load", "action_definition": bravo,
             "share_result": True, "bind_result": True, "return_result": False, "result_limit": 2000},
        ]}
        parallel_tools = types.ModuleType("helpers.parallel_tools")
        parallel_tools._jobs_for_context = lambda context: {
            "alpha-job": types.SimpleNamespace(state="success", tool_name="memory_load"),
            "bravo-job": types.SimpleNamespace(state="running", tool_name="memory_load"),
        }

        with patch.dict(sys.modules, {parallel_tools.__name__: parallel_tools}):
            self.assertTrue(self.runtime.record_host_result(
                agent, "parallel", "x" * 2_000_001))

        self.assertEqual([item["action_id"] for item in state["observations"]], ["alpha"])
        self.assertEqual(state["observations"][0]["binding_result"], "")
        self.assertTrue(state["observations"][0]["truncated"])
        self.assertEqual(self.runtime.pending_parallel_job_ids(agent), ["bravo-job"])
        self.assertTrue(state["complete"])
        self.assertTrue(any(event[0][1] == "parallel_failed" for event in self.timeline_events))

    def test_failed_direct_host_result_is_not_shareable_or_bindable(self):
        action = {"tool_name": "memory_load", "tool_args": {"query": "project"}}
        self.config["policy"]["actions"] = {"lookup": action}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["pending"] = {
            "action_id": "lookup", "tool_name": "memory_load", "action_definition": action,
            "share_result": True, "bind_result": True, "return_result": True, "result_limit": 2000,
        }

        self.assertTrue(self.runtime.record_host_result(
            agent, "memory_load", "ERROR: MCP tool reported failure. unavailable", succeeded=False))
        observation = state["observations"][-1]
        self.assertEqual(observation["result"], "")
        self.assertEqual(observation["binding_result"], "")
        self.assertEqual(observation["return_result"], "")
        self.assertTrue(state["tool_failed"])
        self.assertTrue(state["complete"])

    def test_mcp_failure_text_in_parallel_success_job_is_never_decision_evidence(self):
        action = {"tool_name": "memory_load", "tool_args": {"query": "project"}}
        self.config["policy"]["actions"] = {"lookup": action}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["pending"] = {"tool_name": "parallel", "wait": True,
                            "job_ids": ["lookup-job"], "batch": [
            {"action_id": "lookup", "tool_name": "memory_load", "action_definition": action,
             "share_result": True, "bind_result": True, "return_result": True, "result_limit": 2000},
        ]}
        aggregate = json.dumps({"status": "success", "jobs": [
            {"job_id": "lookup-job", "tool_name": "memory_load", "state": "success",
             "result": "ERROR: MCP tool reported failure. unavailable"},
        ]})

        self.assertTrue(self.runtime.record_host_result(agent, "parallel", aggregate))
        observation = state["observations"][-1]
        self.assertEqual(observation["result"], "")
        self.assertEqual(observation["binding_result"], "")
        self.assertEqual(observation["return_result"], "")
        self.assertTrue(observation["truncated"])
        self.assertTrue(state["complete"])

    def test_native_parallel_error_text_with_success_state_is_not_successful_evidence(self):
        failed = {"tool_name": "skills_tool", "tool_args": {"action": "search", "query": "missing"},
                  "share_result_with_backend": True, "allow_result_bindings": True,
                  "return_result_to_user": True}
        valid = {"tool_name": "memory_load", "tool_args": {"query": "project"},
                 "share_result_with_backend": True, "allow_result_bindings": True,
                 "return_result_to_user": True}
        self.config["policy"]["actions"] = {"failed": failed, "valid": valid}
        agent = Agent()
        state = self.runtime._turn_state(agent, create=True)
        state["pending"] = {"tool_name": "parallel", "wait": True,
                            "job_ids": ["skills-job", "memory-job"], "batch": [
            {"action_id": "failed", "tool_name": "skills_tool", "action_definition": failed,
             "share_result": True, "bind_result": True, "return_result": True, "result_limit": 2000},
            {"action_id": "valid", "tool_name": "memory_load", "action_definition": valid,
             "share_result": True, "bind_result": True, "return_result": True, "result_limit": 2000},
        ]}
        error_signature = self.runtime._call_signature({
            "tool_name": "skills_tool", "tool_args": {"action": "search", "query": "missing"}})
        aggregate = json.dumps({"status": "partial", "jobs": [
            {"job_id": "skills-job", "tool_name": "skills_tool", "state": "success",
             "result": "Error: no matching installed skill"},
            {"job_id": "memory-job", "tool_name": "memory_load", "state": "success",
             "result": "project context"},
        ]})

        self.assertTrue(self.runtime.record_host_result(agent, "parallel", aggregate))
        rejected, accepted = state["observations"]
        self.assertEqual(rejected["action_id"], "failed")
        self.assertEqual(rejected["result"], "")
        self.assertEqual(rejected["binding_result"], "")
        self.assertEqual(rejected["return_result"], "")
        self.assertTrue(rejected["truncated"])
        self.assertEqual(accepted["action_id"], "valid")
        self.assertEqual(accepted["result"], "project context")
        self.assertEqual(accepted["binding_result"], "project context")
        self.assertEqual(accepted["return_result"], "project context")
        self.assertTrue(state["parallel_failed"])
        self.assertTrue(state["complete"])
        self.assertNotIn(error_signature, state.get("committed_signatures", set()))
        self.assertTrue(any(event[0][1] == "parallel_failed" for event in self.timeline_events))


if __name__ == "__main__":
    unittest.main()
