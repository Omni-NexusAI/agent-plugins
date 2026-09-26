import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


BASE = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero"
SOURCE = BASE / "helpers" / "utility.py"
HOOK = BASE / "extensions" / "python" / "util_model_call_before" / "_20_system_1.py"


class OriginalModel:
    def __init__(self):
        self.calls = []

    async def unified_call(self, **kwargs):
        self.calls.append(kwargs)
        return "generated", "reasoning"


class UtilityMemoryTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "utility": {"enabled": True, "backend": "jev", "fixed_routes": []},
            "embedding": {"enabled": False, "backend": "jev"},
            "policy": {"min_choice_probability": 0.85, "max_state_chars": 4000},
        }
        self.choice = types.SimpleNamespace(choice="direct", confidence=0.96)
        self.states = []
        self.agent = types.SimpleNamespace()

        async def choose(state, choices):
            self.states.append((state, choices))
            return self.choice

        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.config_for = lambda agent, section: (
            (self.config[section], self.config["policy"])
            if self.config[section]["enabled"] else None)
        runtime.client_for = lambda section, policy: types.SimpleNamespace(choose=choose)
        self.modules = patch.dict(sys.modules, {
            "usr.plugins.system_1.helpers.runtime": runtime,
        })
        self.modules.start()
        # Execute the edited source directly. A shared checkout can contain a
        # same-second stale .pyc while another focused test imports this helper.
        self.utility = types.ModuleType("utility_memory_under_test")
        self.utility.__file__ = str(SOURCE)
        exec(compile(SOURCE.read_text(encoding="utf-8"), str(SOURCE), "exec"),
             self.utility.__dict__)
        # Other hook tests import this helper through the production module name.
        # Bind our test doubles directly so discovery order cannot retain their
        # previously imported runtime module.
        self.utility.config_for = runtime.config_for
        self.utility.client_for = runtime.client_for

    def tearDown(self):
        self.modules.stop()

    @staticmethod
    def query_prompt(request="where is the project plan", history=""):
        return ("# Provide search query for the following:\n\n## User message:\n"
                f"{request}\n\n## Conversation history for context:\n{history}")

    @staticmethod
    def agent_zero_user_envelope(request="where is the project plan"):
        return f'user: {{"user_message":"{request}"}}'

    @staticmethod
    def agent_zero_history_user_envelope(request="where is the project plan"):
        return f'user: {{"user_message":"{request}"}}'

    @classmethod
    def rendered_query_prompt(cls, request="where is the project plan"):
        return cls.query_prompt(cls.agent_zero_user_envelope(request),
                                cls.agent_zero_history_user_envelope(request))

    @staticmethod
    def filter_prompt(request="find the System 1 plan", history="Earlier chat"):
        return ("# Provide array of indices of relevant memories and solutions in relation "
                "to user message and history:\n\n## Memories and solutions:\n"
                "{0: 'Agent Zero System 1 plan', 1: 'unrelated shopping list', "
                "2: 'System 1 test evidence'}\n\n## User message:\n"
                f"{request}\n\n## History for context:\n{history}")

    def call(self, call_data, callback=None, **overrides):
        return asyncio.run(call_data["model"].unified_call(
            system_message=overrides.get("system_message", call_data["system"]),
            user_message=overrides.get("user_message", call_data["message"]),
            response_callback=callback))

    def test_query_preparation_bypasses_only_the_verified_host_shape(self):
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                     "message": self.rendered_query_prompt(), "model": original}
        self.assertTrue(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, call_data)))
        chunks = []

        async def callback(chunk, total):
            chunks.append((chunk, total))

        self.assertEqual(self.call(call_data, callback),
                         ("where is the project plan", ""))
        self.assertEqual(chunks, [("where is the project plan", "where is the project plan")])
        self.assertEqual(original.calls, [])
        self.assertIn("Direct search query: where is the project plan", self.states[0][0])
        self.assertEqual(self.utility.metrics(self.agent)["bypassed"], 1)

    def test_current_agent_zero_memory_system_templates_match_the_pinned_contracts(self):
        self.assertEqual(self.utility._system_digest(self.utility.MEMORY_QUERY_SYSTEM),
                         "c920bf29d1b70e706ce80cf44cbfa98f5305c554511a106c40ec03c96af75fb4")
        self.assertEqual(self.utility._system_digest(self.utility.MEMORY_FILTER_SYSTEM),
                         "51a5c88bf0370794e2290b553bf91ad72a42d0a5ba4c3875e7022e08addaac9f")
        self.assertEqual(self.utility._INITIAL_BOOTSTRAP_RECORD_CHARS, 545)
        self.assertEqual(self.utility._INITIAL_BOOTSTRAP_RECORD_SHA256,
                         "eea58c02cbaef35f0411521f92b18e523b5ad95bd8da82b56c6996dd7ca36a9d")

    def test_filter_returns_only_a_valid_json_index_list(self):
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_FILTER_SYSTEM,
                     "message": self.filter_prompt(
                         self.agent_zero_user_envelope("find the System 1 plan")),
                     "model": original}
        self.choice = types.SimpleNamespace(choice="keep_0_2", confidence=0.99)
        self.assertTrue(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, call_data)))
        self.assertEqual(self.call(call_data), ("[0,2]", ""))
        self.assertEqual(original.calls, [])
        self.assertIn("Candidate 0: Agent Zero System 1 plan", self.states[0][0])
        self.assertIn("Conversation history: Earlier chat", self.states[0][0])
        self.assertIn("keep_0_2", self.states[0][1])
        self.assertEqual(self.utility.metrics(self.agent)["memory_filter_gate"], {
            "seen": 1, "decision_attempted": 1, "bypass_installed": 1})

    def test_long_candidate_uses_decider_only_when_full_payload_fits(self):
        candidate = "relevant detail " * 70
        self.assertGreater(len(candidate), 800)
        request = self.agent_zero_user_envelope("find the System 1 plan")
        message = self.filter_prompt(request).replace(
            "{0: 'Agent Zero System 1 plan', 1: 'unrelated shopping list', "
            "2: 'System 1 test evidence'}", repr({0: candidate}))
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_FILTER_SYSTEM,
                     "message": message, "model": original}
        self.choice = types.SimpleNamespace(choice="keep_0", confidence=0.99)
        self.assertTrue(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, call_data)))
        self.assertEqual(self.call(call_data), ("[0]", ""))
        self.assertEqual(original.calls, [])

        self.config["policy"]["max_state_chars"] = 200
        oversized = {"system": self.utility.MEMORY_FILTER_SYSTEM,
                     "message": message, "model": OriginalModel()}
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, oversized)))
        self.assertEqual(self.utility.metrics(self.agent)["memory_filter_gate"]
                         ["payload_oversize"], 1)

    def test_low_confidence_filter_preserves_original_utility(self):
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_FILTER_SYSTEM,
                     "message": self.filter_prompt(
                         self.agent_zero_user_envelope("find the System 1 plan")),
                     "model": original}
        self.choice = types.SimpleNamespace(choice="keep_0", confidence=0.4)
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, call_data)))
        self.assertIs(call_data["model"], original)
        gate = self.utility.metrics(self.agent)["memory_filter_gate"]
        self.assertEqual(gate["fallback"], 1)
        self.assertEqual(gate["reason_confidence"], 1)

    def test_malformed_or_unbounded_memory_input_uses_original_utility(self):
        original = OriginalModel()
        malformed = {"system": self.utility.MEMORY_FILTER_SYSTEM,
                     "message": "not the verified Agent Zero prompt", "model": original}
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, malformed)))
        self.assertEqual(self.states, [])
        self.assertEqual(
            self.utility.metrics(self.agent)["memory_filter_gate"]["shape_ineligible"], 1)
        self.assertEqual(
            self.utility.metrics(self.agent)["memory_filter_gate"]["reason_template"], 1)

        self.config["policy"]["max_state_chars"] = 3
        valid_filter = {"system": self.utility.MEMORY_FILTER_SYSTEM,
                        "message": self.filter_prompt(
                            self.agent_zero_user_envelope("find the System 1 plan")),
                        "model": original}
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, valid_filter)))
        self.assertEqual(
            self.utility.metrics(self.agent)["memory_filter_gate"]["payload_oversize"], 1)
        self.config["policy"]["max_state_chars"] = 4000

        oversized = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                     "message": self.query_prompt("word " * 40), "model": original}
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, oversized)))
        self.assertEqual(self.states, [])

    def test_query_with_history_ambiguity_or_changed_system_uses_utility(self):
        for system, message in (
            (self.utility.MEMORY_QUERY_SYSTEM,
             self.query_prompt("what about the other one?", "Earlier plan discussion")),
            (self.utility.MEMORY_QUERY_SYSTEM,
             self.query_prompt("where is the project plan", "Earlier plan discussion")),
            (self.utility.MEMORY_QUERY_SYSTEM, self.query_prompt("hello")),
            (self.utility.MEMORY_QUERY_SYSTEM + "\nchanged", self.query_prompt()),
        ):
            call_data = {"system": system, "message": message, "model": OriginalModel()}
            self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
                self.agent, call_data)))
        self.assertEqual(self.states, [])

    def test_query_rejects_prior_history_but_accepts_only_the_current_host_envelope(self):
        accepted = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                    "message": self.rendered_query_prompt(), "model": OriginalModel()}
        self.assertTrue(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, accepted)))

        envelope = self.agent_zero_user_envelope()
        prior = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                 "message": self.query_prompt(
                     envelope, self.agent_zero_history_user_envelope() + "\nai: Earlier response"),
                 "model": OriginalModel()}
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, prior)))

        changed = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                   "message": self.query_prompt(
                       envelope, self.agent_zero_history_user_envelope("another request")),
                   "model": OriginalModel()}
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, changed)))

    def test_query_accepts_only_pinned_bootstrap_before_the_current_user_record(self):
        request = self.agent_zero_user_envelope()
        bootstrap = "ai: known host bootstrap\n\n"
        history = bootstrap + "\n" + self.agent_zero_history_user_envelope()
        with patch.object(self.utility, "_INITIAL_BOOTSTRAP_RECORD_CHARS", len(bootstrap)), \
             patch.object(self.utility, "_INITIAL_BOOTSTRAP_RECORD_SHA256",
                          self.utility.hashlib.sha256(bootstrap.encode("utf-8")).hexdigest()):
            allowed = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                       "message": self.query_prompt(request, history + "\n"), "model": OriginalModel()}
            self.assertTrue(asyncio.run(self.utility.install_memory_utility_response(
                self.agent, allowed)))
            extra_newline = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                             "message": self.query_prompt(request, history + "\n\n"),
                             "model": OriginalModel()}
            self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
                self.agent, extra_newline)))

        arbitrary_ai = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                        "message": self.query_prompt(
                            request, "ai: unrelated response\n" + self.agent_zero_history_user_envelope()),
                        "model": OriginalModel()}
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, arbitrary_ai)))

    def test_ingestion_remains_generative_and_fallback_is_measured(self):
        original = OriginalModel()
        ingestion = {"system": "HISTORY worth memorizing", "message": "make a summary",
                     "model": original}
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, ingestion)))
        self.assertEqual(self.states, [])

        call_data = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                     "message": self.query_prompt(), "model": original}
        self.choice = types.SimpleNamespace(choice="ordinary", confidence=1.0)
        self.assertFalse(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, call_data)))
        self.assertTrue(self.utility.install_utility_measurement(
            self.agent, call_data, outcome="fallback"))
        self.assertEqual(self.call(call_data), ("generated", "reasoning"))
        record = self.utility.metrics(self.agent)
        self.assertEqual(record["fallbacks"], 1)
        self.assertEqual(record["fallback_model_calls"], 1)
        self.assertGreaterEqual(record["fallback_model_seconds"], 0)
        self.assertEqual(record["model_call_categories"]["memory_query"]["calls"], 1)
        self.assertGreaterEqual(
            record["model_call_categories"]["memory_query"]["seconds"], 0)

    def test_fixed_route_never_bypasses_verified_memory_ingestion(self):
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_SUMMARY_SYSTEM,
                     "message": "USER: Project facts", "model": original}
        self.config["utility"]["fixed_routes"] = [{
            "system": call_data["system"], "message": call_data["message"],
            "responses": {"yes": "[]"},
        }]
        self.choice = types.SimpleNamespace(choice="yes", confidence=1.0)
        self.assertFalse(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, call_data)))
        self.assertEqual(self.states, [])
        self.assertIs(call_data["model"], original)
        self.assertEqual(self.call(call_data), ("generated", "reasoning"))

    def test_fixed_routes_protect_current_and_changed_memory_templates_but_allow_other_calls(self):
        for system in (self.utility.MEMORY_QUERY_SYSTEM,
                       self.utility.MEMORY_FILTER_SYSTEM,
                       self.utility.MEMORY_SUMMARY_SYSTEM):
            self.assertTrue(self.utility._is_protected_memory_system(system))
        changed_summary = self.utility.MEMORY_SUMMARY_SYSTEM + "\n# Host revision"
        self.assertTrue(self.utility._is_protected_memory_system(changed_summary))

        original = OriginalModel()
        call_data = {"system": "Classify exactly", "message": "Item A", "model": original}
        self.config["utility"]["fixed_routes"] = [{
            "system": call_data["system"], "message": call_data["message"],
            "responses": {"yes": "YES"},
        }]
        self.choice = types.SimpleNamespace(choice="yes", confidence=1.0)
        self.assertTrue(asyncio.run(self.utility.install_fixed_utility_response(
            self.agent, call_data)))
        self.assertEqual(self.call(call_data), ("YES", ""))

    def test_embedding_only_guidance_preserves_utility_model_and_memory_work(self):
        self.config["utility"]["enabled"] = False
        self.config["embedding"]["enabled"] = True
        self.choice = types.SimpleNamespace(choice="precise", confidence=0.99)
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_SUMMARY_SYSTEM,
                     "message": "USER: Project facts", "model": original}
        self.assertTrue(asyncio.run(self.utility.install_embedding_memory_guidance(
            self.agent, call_data)))
        self.assertIs(call_data["model"], original)
        self.assertIn("host embedding model and memory index remain authoritative",
                      call_data["system"])
        self.assertIn("Memory operation: memory ingestion", self.states[0][0])
        self.assertEqual(self.utility.metrics(self.agent)["decisions"], 1)

        self.choice = types.SimpleNamespace(choice="normal", confidence=1.0)
        unchanged = {"system": self.utility.MEMORY_SUMMARY_SYSTEM,
                     "message": "USER: More facts", "model": OriginalModel()}
        self.assertFalse(asyncio.run(self.utility.install_embedding_memory_guidance(
            self.agent, unchanged)))
        self.assertEqual(unchanged["system"], self.utility.MEMORY_SUMMARY_SYSTEM)

    def test_embedding_only_hook_guides_ingestion_without_bypassing_utility(self):
        self.config["utility"]["enabled"] = False
        self.config["embedding"]["enabled"] = True
        self.choice = types.SimpleNamespace(choice="precise", confidence=0.99)
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_SUMMARY_SYSTEM,
                     "message": "USER: Project facts", "model": original}
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {
            "__init__": lambda obj, agent: setattr(obj, "agent", agent)})
        with patch.dict(sys.modules, {
            "helpers.extension": extension,
            "usr.plugins.system_1.helpers.utility": self.utility,
        }):
            spec = importlib.util.spec_from_file_location("embedding_guidance_hook", HOOK)
            hook = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hook)
            asyncio.run(hook.SystemOneUtility(self.agent).execute(call_data))
        self.assertIn("System 1 embedding guidance", call_data["system"])
        self.assertEqual(self.call(call_data), ("generated", "reasoning"))
        self.assertEqual(len(original.calls), 1)

    def test_embedding_guidance_never_changes_a_verified_query_bypass(self):
        self.config["embedding"]["enabled"] = True
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                     "message": self.query_prompt(), "model": original}
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {
            "__init__": lambda obj, agent: setattr(obj, "agent", agent)})
        with patch.dict(sys.modules, {
            "helpers.extension": extension,
            "usr.plugins.system_1.helpers.utility": self.utility,
        }):
            spec = importlib.util.spec_from_file_location("embedding_query_hook", HOOK)
            hook = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hook)
            asyncio.run(hook.SystemOneUtility(self.agent).execute(call_data))
        self.assertEqual(call_data["system"], self.utility.MEMORY_QUERY_SYSTEM)
        self.assertEqual(len(self.states), 1)
        self.assertEqual(self.call(call_data), ("where is the project plan", ""))
        self.assertEqual(original.calls, [])

    def test_changed_call_falls_back_and_metrics_keep_no_content(self):
        original = OriginalModel()
        call_data = {"system": self.utility.MEMORY_QUERY_SYSTEM,
                     "message": self.query_prompt(), "model": original}
        self.assertTrue(asyncio.run(self.utility.install_memory_utility_response(
            self.agent, call_data)))
        self.assertEqual(self.call(call_data, user_message=self.query_prompt("different request")),
                         ("generated", "reasoning"))
        record = self.utility.metrics(self.agent)
        self.assertEqual(record["fallbacks"], 1)
        self.assertNotIn("prompt", record)
        self.assertNotIn("response", record)
        self.assertNotIn("credential", record)


if __name__ == "__main__":
    unittest.main()
