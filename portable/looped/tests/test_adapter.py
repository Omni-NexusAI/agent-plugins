"""Agent Zero adapter tests, run against an assembled copy outside the monorepo.

The host is replaced by small fakes, so these check the adapter's contract with
both host generations: a tuple from ``call_chat_model`` and an ``LLMResult``
from ``call_chat_model_turn``.
"""

import asyncio
import importlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import support  # noqa: F401
from core import DEFAULTS
from support import final, step

LOOPED = Path(__file__).resolve().parents[1]
ADAPTER = LOOPED / "adapters" / "agent_zero"
SAVED = {"settings": {}}


class FakeLLMResult:
    def __init__(self, response="", reasoning="", output_items=None, usage=None):
        self.response, self.reasoning = response, reasoning
        self.output_items = output_items or []
        self.usage = usage

    @classmethod
    def from_chat(cls, *, response, reasoning="", usage=None, **_):
        return cls(response=response, reasoning=reasoning, usage=usage)


class HumanMessage:
    def __init__(self, content):
        self.content = content


class Extension:
    def __init__(self, agent=None, **kwargs):
        self.agent = agent


def _install_host_fakes():
    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        sys.modules[name] = mod
        return mod
    helpers = module("helpers")
    helpers.__path__ = []
    helpers.plugins = module("helpers.plugins",
                             get_plugin_config=lambda name, agent=None: SAVED["settings"])
    helpers.llm_result = module("helpers.llm_result", LLMResult=FakeLLMResult)
    helpers.extension = module("helpers.extension", Extension=Extension)
    core_pkg = module("langchain_core")
    core_pkg.__path__ = []
    core_pkg.messages = module("langchain_core.messages", HumanMessage=HumanMessage)


_TMP = tempfile.TemporaryDirectory()
_DEST = Path(_TMP.name) / "looped"
subprocess.run([sys.executable, str(LOOPED / "assemble.py"), "--dest", str(_DEST)],
               check=True, capture_output=True)
sys.path.insert(0, _TMP.name)
_install_host_fakes()
runtime = importlib.import_module("looped.helpers.runtime")
command = importlib.import_module("looped.helpers.command")


class FakeModel:
    def __init__(self, replies=()):
        self.replies = list(replies)
        self.calls = []

    async def unified_call(self, system_message="", user_message="", messages=None, **kwargs):
        messages = messages if messages is not None else []
        messages.append("mutated-by-wrapper")   # the real wrapper mutates its list
        self.calls.append({"system": system_message, "user": user_message,
                           "messages": messages, "kwargs": kwargs})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, ""


class FakeLog:
    def __init__(self):
        self.items = []

    def log(self, **kwargs):
        self.items.append(kwargs)


class FakeAgent:
    def __init__(self, model, number=0, chat=None):
        self.number = number
        self.model = model
        self.context = types.SimpleNamespace(id="ctx-1", data=chat if chat is not None else {},
                                             log=FakeLog())
        self.loop_data = types.SimpleNamespace(
            iteration=0, params_temporary={}, extras_temporary={}, extras_persistent={},
            last_response="", user_message=types.SimpleNamespace(
                content={"user_message": "Write the report."}))
        self.streamed = []

    def get_chat_model(self):
        return self.model

    async def handle_response_stream(self, text):
        self.streamed.append(text)


def run(coro):
    return asyncio.run(coro)


def main_call(agent, result, messages=None, **kwargs):
    runtime.mark_main_call(agent, agent.loop_data)
    return {"args": (agent,), "kwargs": {"messages": messages if messages is not None else ["sys", "user"],
                                         **kwargs},
            "result": result, "exception": None}


class AdapterCase(unittest.TestCase):
    def setUp(self):
        SAVED["settings"] = {"mode": "always"}
        runtime._metrics.clear()


class CallEndTests(AdapterCase):
    def test_agreement_leaves_the_host_result_untouched(self):
        a = step("write", path="a.txt")
        agent = FakeAgent(FakeModel([a]))
        original = (a, "")
        data = main_call(agent, original)
        run(runtime.on_call_end(agent, data, turn=False))
        self.assertIs(data["result"], original)
        self.assertEqual(len(agent.model.calls), 1)
        self.assertEqual(agent.context.log.items[0]["heading"], "Looped: both passes agree")
        self.assertNotIn(runtime.MAIN_CALL, agent.loop_data.params_temporary)

    def test_winning_second_pass_replaces_a_tuple_result(self):
        a, b = step("write", path="a.txt"), step("write", path="b.txt")
        agent = FakeAgent(FakeModel([b + " trailing prose }", b]))
        data = main_call(agent, (a, "why"))
        run(runtime.on_call_end(agent, data, turn=False))
        text, reasoning = data["result"]
        self.assertEqual(json.loads(text)["tool_args"], {"path": "b.txt"})
        self.assertEqual(reasoning, "why")
        run(runtime.on_stream_end(agent, agent.loop_data))
        self.assertEqual(agent.streamed, [text])
        self.assertEqual(runtime.metrics_report("ctx-1")["changed"], 1)

    def test_winning_second_pass_replaces_a_structured_result(self):
        a, b = step("write", path="a.txt"), step("write", path="b.txt")
        agent = FakeAgent(FakeModel([b, b]))
        data = main_call(agent, FakeLLMResult(response=a, usage={"total": 5}))
        run(runtime.on_call_end(agent, data, turn=True))
        self.assertIsInstance(data["result"], FakeLLMResult)
        self.assertEqual(json.loads(data["result"].response)["tool_args"], {"path": "b.txt"})
        self.assertEqual(data["result"].usage, {"total": 5})

    def test_unsure_quick_passes_ask_once_more_with_reasoning_switched_on(self):
        SAVED["settings"] = {"mode": "always", "strategies": {"escalate": {"enabled": True}}}
        a, b, c = step("write", path="a.txt"), step("write", path="b.txt"), step("write", path="c.txt")
        agent = FakeAgent(FakeModel([b, c]))
        data = main_call(agent, (a, ""))
        run(runtime.on_call_end(agent, data, turn=False))
        self.assertEqual(json.loads(data["result"][0])["tool_args"], {"path": "c.txt"})
        quick, careful = agent.model.calls
        self.assertIn("seed", quick["kwargs"])
        self.assertEqual(careful["kwargs"],
                         {"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}})
        self.assertEqual(agent.context.log.items[0]["heading"],
                         "Looped: quick passes were unsure, used the reasoned pass")
        agent = FakeAgent(FakeModel([a]))                    # agreement: no reasoning call
        run(runtime.on_call_end(agent, main_call(agent, (a, "")), turn=False))
        self.assertEqual(len(agent.model.calls), 1)

    def test_native_function_calls_pass_through(self):
        agent = FakeAgent(FakeModel())
        result = FakeLLMResult(response="", output_items=[types.SimpleNamespace(type="function_call")])
        data = main_call(agent, result)
        run(runtime.on_call_end(agent, data, turn=True))
        self.assertIs(data["result"], result)
        self.assertEqual(agent.model.calls, [])

    def test_other_calls_are_ignored(self):
        a = step("write", path="a.txt")
        agent = FakeAgent(FakeModel())
        unmarked = {"args": (agent,), "kwargs": {"messages": []}, "result": (a, ""), "exception": None}
        run(runtime.on_call_end(agent, unmarked, turn=False))
        background = main_call(agent, (a, ""), background=True)
        run(runtime.on_call_end(agent, background, turn=False))
        failed = main_call(agent, None)
        failed["exception"] = RuntimeError("provider down")
        run(runtime.on_call_end(agent, failed, turn=False))
        self.assertEqual(agent.model.calls, [])

    def test_manual_mode_needs_the_arm_and_the_arm_lasts_one_turn(self):
        SAVED["settings"] = {}
        a = step("write", path="a.txt")
        agent = FakeAgent(FakeModel([a]))
        runtime.begin_turn(agent)
        run(runtime.on_call_end(agent, main_call(agent, (a, "")), turn=False))
        self.assertEqual(agent.model.calls, [])

        self.assertEqual(command.handle(agent.context.data, "/looped fix it"),
                         ("fix it", "Looped mode is on for this message."))
        runtime.begin_turn(agent)
        run(runtime.on_call_end(agent, main_call(agent, (a, "")), turn=False))
        self.assertEqual(len(agent.model.calls), 1)
        runtime.end_turn(agent)
        runtime.begin_turn(agent)
        run(runtime.on_call_end(agent, main_call(agent, (a, "")), turn=False))
        self.assertEqual(len(agent.model.calls), 1)

    def test_chat_mode_overrides_the_saved_default(self):
        SAVED["settings"] = {"mode": "off"}
        a = step("write", path="a.txt")
        agent = FakeAgent(FakeModel([a]), chat={command.MODE_KEY: "always"})
        run(runtime.on_call_end(agent, main_call(agent, (a, "")), turn=False))
        self.assertEqual(len(agent.model.calls), 1)

    def test_subordinates_are_skipped_unless_enabled(self):
        a = step("write", path="a.txt")
        agent = FakeAgent(FakeModel([a]), number=1)
        run(runtime.on_call_end(agent, main_call(agent, (a, "")), turn=False))
        self.assertEqual(agent.model.calls, [])
        SAVED["settings"] = {"mode": "always", "apply_to_subordinates": True}
        run(runtime.on_call_end(agent, main_call(agent, (a, "")), turn=False))
        self.assertEqual(len(agent.model.calls), 1)

    def test_extra_calls_copy_the_prompt_and_vary_sampling(self):
        a = step("write", path="a.txt")
        messages = ["sys", "user"]
        agent = FakeAgent(FakeModel([a]))
        run(runtime.on_call_end(agent, main_call(agent, (a, ""), messages=messages), turn=False))
        self.assertEqual(messages, ["sys", "user"])
        self.assertEqual(agent.model.calls[0]["kwargs"], {"seed": 1001, "temperature": 0.7})

    def test_rejected_sampling_overrides_are_retried_without_them(self):
        a = step("write", path="a.txt")
        agent = FakeAgent(FakeModel([ValueError("seed unsupported"), a]))
        data = main_call(agent, (a, ""))
        run(runtime.on_call_end(agent, data, turn=False))
        self.assertEqual(agent.model.calls[1]["kwargs"], {})
        self.assertIn("both passes agree", agent.context.log.items[0]["heading"])

    def test_a_failing_model_never_breaks_the_step(self):
        a = step("write", path="a.txt")
        agent = FakeAgent(FakeModel([RuntimeError("down"), RuntimeError("down")]))
        original = (a, "")
        data = main_call(agent, original)
        run(runtime.on_call_end(agent, data, turn=False))
        self.assertIs(data["result"], original)

    def test_long_final_answers_are_merged_with_the_drafts_in_the_prompt(self):
        first, second = final("Alpha point. " * 40), final("Beta point. " * 40)
        agent = FakeAgent(FakeModel([second, final("Merged.")]))
        data = main_call(agent, (first, ""))
        run(runtime.on_call_end(agent, data, turn=False))
        self.assertEqual(json.loads(data["result"][0])["tool_args"]["text"], "Merged.")
        note = agent.model.calls[1]["messages"][2]
        self.assertIsInstance(note, HumanMessage)
        self.assertIn("Draft 2:", note.content)

    def test_timeline_step_can_be_limited_to_changes(self):
        SAVED["settings"] = {"mode": "always", "show_steps": "changed"}
        a = step("write", path="a.txt")
        agent = FakeAgent(FakeModel([a]))
        run(runtime.on_call_end(agent, main_call(agent, (a, "")), turn=False))
        self.assertEqual(agent.context.log.items, [])


class ParallelTests(AdapterCase):
    def test_parallel_execution_starts_and_reuses_an_early_second_pass(self):
        SAVED["settings"] = {"mode": "always", "execution": "parallel"}
        a = step("write", path="a.txt")

        async def scenario():
            agent = FakeAgent(FakeModel([a]))
            data = main_call(agent, None)
            await runtime.on_call_start(agent, data)
            self.assertIn(runtime.EARLY, agent.loop_data.params_temporary)
            data["result"] = (a, "")
            await runtime.on_call_end(agent, data, turn=False)
            return agent
        agent = run(scenario())
        self.assertEqual(len(agent.model.calls), 1)
        self.assertNotIn(runtime.EARLY, agent.loop_data.params_temporary)

    def test_sequential_execution_starts_nothing_early(self):
        agent = FakeAgent(FakeModel())
        run(runtime.on_call_start(agent, main_call(agent, None)))
        self.assertNotIn(runtime.EARLY, agent.loop_data.params_temporary)

    def test_early_pass_is_cancelled_when_the_host_call_fails(self):
        SAVED["settings"] = {"mode": "always", "execution": "parallel"}

        async def scenario():
            agent = FakeAgent(FakeModel())
            data = main_call(agent, None)
            await runtime.on_call_start(agent, data)
            task = agent.loop_data.params_temporary[runtime.EARLY]
            data["exception"] = RuntimeError("provider down")
            await runtime.on_call_end(agent, data, turn=False)
            await asyncio.sleep(0)
            return task, agent
        task, agent = run(scenario())
        self.assertTrue(task.cancelled())
        self.assertEqual(agent.model.calls, [])


class PromptAndToolTests(AdapterCase):
    def test_reread_block_is_added_while_active(self):
        agent = FakeAgent(FakeModel())
        run(runtime.on_prompt(agent, agent.loop_data))
        self.assertIn("Write the report.", agent.loop_data.extras_temporary["looped_reread"])

    def test_nothing_is_added_while_inactive_or_once_reasoning_was_seen(self):
        SAVED["settings"] = {}
        agent = FakeAgent(FakeModel())
        runtime.begin_turn(agent)
        run(runtime.on_prompt(agent, agent.loop_data))
        self.assertEqual(agent.loop_data.extras_temporary, {})
        SAVED["settings"] = {"mode": "always"}
        agent = FakeAgent(FakeModel(), chat={runtime.SAW_REASONING: True})
        run(runtime.on_prompt(agent, agent.loop_data))
        self.assertEqual(agent.loop_data.extras_temporary, {})

    def test_tool_error_arms_a_second_look_and_a_note(self):
        SAVED["settings"] = {"mode": "auto"}
        agent = FakeAgent(FakeModel())
        runtime.begin_turn(agent)
        runtime.on_tool_result(agent, types.SimpleNamespace(message="Traceback (most recent call last):"))
        self.assertTrue(runtime.state(agent).retry_armed)
        run(runtime.on_prompt(agent, agent.loop_data))
        self.assertIn("looped_retry", agent.loop_data.extras_temporary)

    def test_parallel_planning_adds_one_persistent_note(self):
        SAVED["settings"] = {"mode": "always", "strategies": {"plan_branch": {"enabled": True}}}
        agent = FakeAgent(FakeModel(["1. a", "1. b", "1. merged"]))
        runtime.begin_turn(agent)
        run(runtime.on_prompt(agent, agent.loop_data))
        self.assertIn("1. merged", agent.loop_data.extras_persistent["looped_plan"])
        self.assertEqual(agent.model.calls[0]["user"], "Write the report.")
        self.assertEqual(len(agent.model.calls), 3)


class CommandTests(unittest.TestCase):
    def test_parsing(self):
        cases = {
            "/looped": ("arm", None, ""),
            "  /LOOPED fix the bug": ("arm", None, "fix the bug"),
            "/looped once do it": ("arm", None, "do it"),
            "/looped on": ("mode", "always", ""),
            "/looped auto and then go": ("mode", "auto", "and then go"),
            "/looped off": ("mode", "off", ""),
            "/looped status": ("status", None, ""),
            "fix the bug /looped": ("arm", None, "fix the bug"),
        }
        for text, expected in cases.items():
            self.assertEqual(command.parse(text), expected, text)
        for text in ("/loopedx", "use /looped in the middle of text", "plain", "", None,
                     "path/looped"):
            self.assertIsNone(command.parse(text), text)

    def test_applying(self):
        chat = {}
        self.assertEqual(command.handle(chat, "/looped"), ("", "Looped mode armed for your next message."))
        self.assertTrue(chat[command.ARM_KEY])
        command.handle(chat, "/looped auto")
        self.assertEqual(chat[command.MODE_KEY], "auto")
        self.assertIn("auto (this chat), armed", command.handle(chat, "/looped status")[1])
        command.handle(chat, "/looped off")
        self.assertNotIn(command.ARM_KEY, chat)
        self.assertIsNone(command.handle(chat, "hello"))

    def test_backend_hook_strips_the_command_or_ends_the_chain(self):
        path = _DEST / "extensions/python/_functions/agent/AgentContext/_process_chain/start/_05_looped_command.py"
        spec = importlib.util.spec_from_file_location("looped_command_hook", path)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        # The hook imports the plugin by its installed name.
        usr = types.ModuleType("usr"); usr.__path__ = []
        plugins = types.ModuleType("usr.plugins"); plugins.__path__ = [_TMP.name]
        sys.modules.update({"usr": usr, "usr.plugins": plugins})
        SAVED["settings"] = {}

        def call(text, number=0, user=True):
            context = types.SimpleNamespace(data={})
            agent = types.SimpleNamespace(number=number)
            message = types.SimpleNamespace(message=text, attachments=[])
            data = {"args": (context, agent, message, user), "kwargs": {}, "result": "UNSET"}
            run(hook.LoopedCommand(agent=agent).execute(data=data))
            return context.data, message.message, data["result"]

        chat, text, result = call("/looped fix the bug")
        self.assertEqual((chat, text, result), ({command.ARM_KEY: True}, "fix the bug", "UNSET"))
        chat, text, result = call("/looped auto")
        self.assertEqual((chat[command.MODE_KEY], result), ("auto", "Looped mode set to auto for this chat."))
        self.assertEqual(call("hello")[1:], ("hello", "UNSET"))
        self.assertEqual(call("/looped x", number=1)[0], {})
        self.assertEqual(call("/looped x", user=False)[0], {})


class PackagingTests(unittest.TestCase):
    def test_default_config_file_matches_core_defaults(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        loaded = yaml.safe_load((ADAPTER / "default_config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(loaded, DEFAULTS)

    def test_settings_page_defaults_match_core_defaults(self):
        html = (ADAPTER / "webui" / "config.html").read_text(encoding="utf-8")
        found = re.search(r"const DEFAULTS = (\{.*\});", html)
        self.assertEqual(json.loads(found.group(1)), DEFAULTS)

    def test_assembled_package_is_self_contained(self):
        names = {path.relative_to(_DEST).as_posix() for path in _DEST.rglob("*") if path.is_file()}
        for needed in ("plugin.yaml", "default_config.yaml", "helpers/runtime.py",
                       "helpers/looped_core/pipeline.py", "helpers/looped_core/strategies/agree.py",
                       "commands/looped.command.yaml", "webui/config.html", "api/mode.py"):
            self.assertIn(needed, names)
        for path in _DEST.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("portable", source, path)
            compile(source, str(path), "exec")

    def test_manifest_name_matches_the_package_folder(self):
        manifest = (ADAPTER / "plugin.yaml").read_text(encoding="utf-8")
        self.assertRegex(manifest, r"(?m)^name: looped$")


if __name__ == "__main__":
    unittest.main()
