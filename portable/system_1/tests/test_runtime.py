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
        tool_availability = types.ModuleType("usr.plugins.system_1.helpers.tool_availability")
        tool_availability.is_tool_available = lambda agent, tool_name: True
        auxiliary = types.ModuleType("usr.plugins.auxiliary_model_roles.helpers.runtime")
        auxiliary.available_roles = lambda agent: {"tool": {"enabled": True}}
        self.modules = patch.dict(sys.modules, {"helpers": helpers, core.__name__: core,
                                                decision.__name__: decision, timeline.__name__: timeline,
                                                tool_availability.__name__: tool_availability,
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


if __name__ == "__main__":
    unittest.main()
