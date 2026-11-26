import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401

BENCH = Path(__file__).resolve().parents[1] / "bench"
sys.path.insert(0, str(BENCH))

import gate  # noqa: E402
import multistep  # noqa: E402
import run_bench  # noqa: E402
import stats  # noqa: E402
import tasks as task_sets  # noqa: E402
from core import build_candidate  # noqa: E402
from support import final, step  # noqa: E402


class TaskTests(unittest.TestCase):
    def test_generated_sets_are_deterministic_and_splits_do_not_overlap(self):
        for suite in ("arith", "tool"):
            dev = task_sets.generated(suite, 40, seed=3, split="dev")
            held = task_sets.generated(suite, 40, seed=3, split="heldout")
            self.assertEqual([t.id for t in dev], [t.id for t in task_sets.generated(suite, 40, 3, "dev")])
            self.assertEqual(len(dev), 40)
            self.assertFalse({t.id for t in dev} & {t.id for t in held})

    def test_jsonl_loader_handles_choices_and_tool_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mini.jsonl"
            path.write_text(
                '{"id": "q1", "question": "Pick", "choices": ["x", "y"], "answer": "B"}\n'
                '{"id": "t1", "kind": "tool", "question": "Read a.txt", "tool_name": "read_file", '
                '"tool_args": {"path": "a.txt"}}\n', encoding="utf-8")
            loaded = task_sets.from_jsonl(path)
        self.assertIn("B. y", loaded[0].question)
        self.assertEqual((loaded[1].kind, loaded[1].suite), ("tool", "mini"))


class ScoreTests(unittest.TestCase):
    def test_scoring(self):
        number = task_sets.Task("a", "qa", "q", answer="1,234")
        letter = task_sets.Task("b", "qa", "q", answer="B")
        tool = task_sets.Task("c", "tool", "q", tool_name="read_file", tool_args={"path": "a.txt"})
        self.assertTrue(run_bench.score(number, build_candidate(final("**1234**."))))
        self.assertFalse(run_bench.score(number, build_candidate(final("1235"))))
        self.assertTrue(run_bench.score(task_sets.Task("d", "qa", "q", answer="5"),
                                        build_candidate(final("5.00"))))
        self.assertTrue(run_bench.score(letter, build_candidate(final("B. y"))))
        self.assertFalse(run_bench.score(letter, build_candidate(final("Because"))))
        self.assertTrue(run_bench.score(tool, build_candidate(step("read_file", path="a.txt "))))
        self.assertFalse(run_bench.score(tool, build_candidate(step("read_file", path="b.txt"))))
        self.assertFalse(run_bench.score(tool, build_candidate("not json")))
        self.assertFalse(run_bench.score(number, build_candidate(step("read_file", path="1,234"))))


class StatsTests(unittest.TestCase):
    def test_paired_counts_and_exact_test(self):
        result = stats.paired([True, False, False, True], [True, True, True, False])
        self.assertEqual((result["fixed"], result["broke"]), (2, 1))
        self.assertEqual(stats.mcnemar_exact(0, 0), 1.0)
        self.assertAlmostEqual(stats.mcnemar_exact(10, 0), 2 / 2 ** 10)
        self.assertEqual(stats.mcnemar_exact(5, 5), 1.0)

    def test_bootstrap_interval_brackets_the_mean(self):
        low, high = stats.bootstrap_ci([True] * 70 + [False] * 30)
        self.assertTrue(0.55 < low < 0.7 < high < 0.85)
        self.assertEqual(stats.bootstrap_ci([]), (0.0, 0.0))


class DryRunTests(unittest.TestCase):
    def test_dry_run_produces_every_arm_for_every_suite(self):
        with tempfile.TemporaryDirectory() as folder:
            args = run_bench.parse(["--dry-run", "--tasks", "30", "--out", folder])

            def make_client(items):
                from clients import SimulatedModel
                return SimulatedModel({task.question: task for task in items}, seed=1)
            table = asyncio.run(run_bench.run(args, make_client))
        self.assertEqual({(row["suite"], row["arm"]) for row in table},
                         {(suite, arm) for suite in ("arith", "tool") for arm in args.arms})
        self.assertEqual(args.arms, ["plain", "reread", "agree", "deepen", "stack"])
        by_arm = {(row["suite"], row["arm"]): row for row in table}
        self.assertEqual(by_arm[("tool", "plain")]["calls_per_task"], 1.0)
        self.assertEqual(by_arm[("tool", "reread")]["calls_per_task"], 1.0)
        self.assertGreater(by_arm[("tool", "agree")]["calls_per_task"], 2.0)
        self.assertEqual(by_arm[("tool", "deepen")]["calls_per_task"], 2.0)
        self.assertIn("fixed", by_arm[("arith", "agree")])
        self.assertIn("| arith | agree |", run_bench.markdown(table, "t"))

    def test_shared_first_pass_reuses_the_plain_reply(self):
        class Counting:
            prompt_tokens = completion_tokens = 0

            def __init__(self):
                self.calls = 0

            async def complete(self, messages, **kwargs):
                self.calls += 1
                return '{"tool_name": "response", "tool_args": {"text": "%d"}}' % self.calls, ""

        items = task_sets.generated("arith", 3, 7, "dev")
        shared, plain, agree = run_bench.Replies(), Counting(), Counting()
        asyncio.run(run_bench.run_arm("plain", items, plain, 1, shared=shared))
        self.assertEqual(set(shared.held), {("plain", task.id) for task in items})
        result = asyncio.run(run_bench.run_arm("agree", items, agree, 1, shared=shared))
        self.assertEqual(sum(row["calls"] for row in result["rows"]) - len(items), agree.calls)
        self.assertGreaterEqual(agree.calls, len(items))        # second passes only
        separate = Counting()
        asyncio.run(run_bench.run_arm("reread", items, separate, 1, shared=shared))
        self.assertEqual(separate.calls, len(items))            # different prompt: not shared

    def test_think_arm_reasons_and_replies_are_kept_for_a_later_run(self):
        class Recording:
            prompt_tokens = completion_tokens = 0
            last_tokens = 7

            def __init__(self):
                self.options = []

            async def complete(self, messages, **kwargs):
                self.options.append(kwargs)
                return '{"tool_name": "response", "tool_args": {"text": "1"}}', "because"

        items = task_sets.generated("arith", 2, 7, "dev")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "replies.jsonl"
            first = Recording()
            result = asyncio.run(run_bench.run_arm("think", items, first, 1,
                                                   shared=run_bench.Replies(path), think_tokens=900))
            self.assertEqual(first.options, [{"thinking": True, "max_tokens": 900}] * 2)
            self.assertEqual({row["outcome"] for row in result["rows"]}, {"think"})
            later, again = run_bench.Replies(path), Recording()
            asyncio.run(run_bench.run_arm("think", items, again, 1, shared=later, think_tokens=900))
            self.assertEqual(again.options, [])                 # read back, not asked again
            self.assertEqual(later.tokens[("think", items[0].id)], 7)
            self.assertIsNone(later.get("plain", items[0].id))  # quick replies are kept apart

    def test_carry_arm_shares_quick_passes_and_reasons_with_a_note(self):
        right = '{"tool_name": "response", "tool_args": {"text": "%s"}}'

        class Scripted:
            prompt_tokens = 0
            last_tokens = 5

            def __init__(self, replies):
                self.replies, self.seen, self.completion_tokens = list(replies), [], 0

            async def complete(self, messages, **kwargs):
                self.seen.append((messages, kwargs))
                self.completion_tokens += self.last_tokens
                return self.replies.pop(0)

        task = task_sets.generated("arith", 1, 7, "dev")[0]
        shared = run_bench.Replies()
        shared.put("plain", task.id, right % "0", "", 5)
        escalate = Scripted([(right % "1", ""), (right % task.answer, "why")])
        row = asyncio.run(run_bench.episode(task, run_bench.ARMS["escalate"], escalate, shared))
        self.assertEqual((row["outcome"], row["correct"], row["tokens"]), ("reasoned", True, 10))
        self.assertEqual(shared.get("second", task.id)[0], right % "1")     # kept for other arms
        self.assertEqual(len(escalate.seen[1][0]), len(task_sets.messages(task)))

        carry = Scripted([("", "notes so far"), (right % task.answer, "")])
        row = asyncio.run(run_bench.episode(task, run_bench.ARMS["carry"], carry, shared,
                                            think_tokens=900))
        self.assertEqual((row["outcome"], row["correct"], row["calls"]), ("rescued", True, 4))
        (reasoned, options), (rescue, quick) = carry.seen                   # second pass not re-asked
        self.assertEqual(options, {"thinking": True, "max_tokens": 900})
        self.assertIn(right % "0", reasoned[-1]["content"])
        self.assertIn(right % "1", reasoned[-1]["content"])
        self.assertIn("notes so far", rescue[-1]["content"])
        self.assertNotIn("thinking", quick)

    def test_a_kept_reasoning_reply_over_the_limit_counts_as_cut_off(self):
        task = task_sets.generated("arith", 1, 7, "dev")[0]
        shared = run_bench.Replies()
        shared.put("think", task.id, '{"tool_name": "response", "tool_args": {"text": "%s"}}'
                   % task.answer, "x" * 1000, 5000)
        row = asyncio.run(run_bench.episode(task, run_bench.ARMS["think"], None, shared,
                                            think_tokens=6000))
        self.assertTrue(row["correct"])
        row = asyncio.run(run_bench.episode(task, run_bench.ARMS["think"], None, shared,
                                            think_tokens=2500))
        self.assertFalse(row["correct"])
        self.assertTrue(row["given"].startswith("(invalid)"))

    def test_malformed_replies_are_counted_apart_from_wrong_answers(self):
        rows = [{"correct": True, "calls": 1, "outcome": "plain", "given": "7"},
                {"correct": False, "calls": 1, "outcome": "plain", "given": "(invalid) 7"},
                {"correct": False, "calls": 1, "outcome": "plain", "given": "8"}]
        result = {"rows": rows, "seconds": 1.0, "prompt_tokens": 0, "completion_tokens": 0}
        table = run_bench.summarise("s", {"plain": result})
        self.assertEqual(table[0]["malformed"], 1)
        self.assertIn("| Malformed |", run_bench.markdown(table, "t"))

    def test_a_dead_server_stops_the_run_and_keeps_the_rows(self):
        class Dying:
            prompt_tokens = completion_tokens = 0

            def __init__(self):
                self.calls = 0

            async def complete(self, messages, **kwargs):
                self.calls += 1
                if self.calls > 4:
                    raise TimeoutError("no reply")
                return '{"tool_name": "response", "tool_args": {"text": "1"}}', ""

        items = task_sets.generated("arith", 20, 7, "dev")
        client, kept = Dying(), []
        with self.assertRaises(run_bench.ServerDown):
            asyncio.run(run_bench.run_arm("plain", items, client, 1,
                                          on_row=lambda arm, row: kept.append(row), max_errors=3))
        self.assertEqual(client.calls, 7)       # 4 answered, 3 failed, then no more requests
        self.assertEqual(len(kept), 7)
        self.assertEqual(sum(row["outcome"].startswith("error") for row in kept), 3)

    def test_live_needs_an_endpoint_and_model(self):
        with self.assertRaises(SystemExit):
            run_bench.parse(["--live"])


class Scripted:
    """Plays a multi-step task's own solution, one step per prompt."""

    prompt_tokens = completion_tokens = 0

    def __init__(self, task, first=()):
        self.task, self.first, self.calls = task, list(first), 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        if self.first:
            return self.first.pop(0), ""
        taken = sum(1 for m in messages if m["role"] == "assistant" and m["content"].startswith("{"))
        tool, args = self.task.script[min(taken, len(self.task.script) - 1)]
        return step(tool, **args), ""


class MultiStepTests(unittest.TestCase):
    def test_every_task_passes_with_its_own_solution_and_both_splits_have_every_form(self):
        dev = task_sets.generated("multi", 20, seed=3, split="dev")
        held = task_sets.generated("multi", 20, seed=3, split="heldout")
        self.assertEqual([t.question for t in dev],
                         [t.question for t in task_sets.generated("multi", 20, 3, "dev")])
        self.assertFalse({t.id for t in dev} & {t.id for t in held})
        for tasks in (dev, held):
            self.assertEqual({t.form for t in tasks}, set(multistep.FORMS))
        for task in dev + held:
            world = task.world()
            for tool, args in task.script[:-1]:
                self.assertFalse(world.run(tool, args).startswith("Error"), task.id)
            self.assertEqual(task.failures(world), [], task.id)
            self.assertEqual(task.script[-1], ("response", {"text": task.answer}))
            self.assertTrue(run_bench.score(task, build_candidate(final(task.answer))))
            self.assertGreaterEqual(len(task.script), 5)

    def test_the_world_reports_errors_and_one_wrong_step_fails_the_task(self):
        task = next(t for t in task_sets.generated("multi", 10, 3, "dev") if t.form == "cleanup")
        world = task.world()
        self.assertEqual(world.run("read_file", {"path": "missing.txt"}),
                         "Error: no such file: missing.txt")
        self.assertIn("unknown tool", world.run("run_shell", {"command": "ls"}))
        self.assertIn("needs a path", world.run("delete_file", {}))
        for tool, args in task.script[:-1]:
            world.run(tool, args)
        kept = task.files[task.script[1][1]["path"]].splitlines()[0]
        world.run("delete_file", {"path": "./" + kept})
        self.assertEqual(task.failures(world), ["files"])
        ledger = next(t for t in task_sets.generated("multi", 10, 3, "dev") if t.form == "ledger")
        world = ledger.world()
        world.run("write_file", {"path": ledger.script[2][1]["path"], "text": f" {ledger.answer}.0 "})
        self.assertEqual(ledger.failures(world), ["messages"])     # 1234.0 is 1234; nothing sent

    def test_an_episode_runs_steps_until_the_answer(self):
        task = task_sets.generated("multi", 4, 3, "dev")[1]
        plain = run_bench.ARMS["plain"]
        row = asyncio.run(run_bench.episode(task, plain, Scripted(task)))
        self.assertEqual((row["correct"], row["outcome"], row["steps"], row["calls"]),
                         (True, "passed", len(task.script), len(task.script)))
        self.assertEqual(row["resolved"], {"plain": len(task.script)})
        slip = asyncio.run(run_bench.episode(task, plain, Scripted(task, ["not a step"])))
        self.assertEqual((slip["correct"], slip["steps"]), (True, len(task.script) + 1))
        again = step("read_file", path=task.script[0][1]["path"])
        stuck = asyncio.run(run_bench.episode(task, plain, Scripted(task, [again] * 50)))
        self.assertEqual((stuck["correct"], stuck["steps"], stuck["given"]),
                         (False, task.max_steps, "(no answer)"))
        self.assertTrue(stuck["outcome"].startswith("failed: no_answer"))
        wrong = asyncio.run(run_bench.episode(task, plain, Scripted(task, [final("nonsense")])))
        self.assertFalse(wrong["correct"])
        self.assertTrue(wrong["outcome"].startswith("failed: answer"))

    def test_arms_share_a_step_while_they_have_taken_the_same_steps(self):
        task = task_sets.generated("multi", 4, 3, "dev")[0]
        shared, first, second = run_bench.Replies(), Scripted(task), Scripted(task)
        asyncio.run(run_bench.run_arm("plain", [task], first, 1, shared=shared))
        result = asyncio.run(run_bench.run_arm("escalate", [task], second, 1, shared=shared))
        row = result["rows"][0]
        steps = len(task.script)
        self.assertEqual(second.calls, steps)                   # the second quick passes only
        self.assertEqual((row["correct"], row["calls"]), (True, 2 * steps))
        self.assertEqual(row["resolved"], {"agreed": steps})
        self.assertEqual(len({key for kind, key in shared.held if kind == "plain"}), steps)

    def test_every_step_of_a_long_task_is_looked_at(self):
        task = max(task_sets.generated("multi", 10, 3, "dev"), key=lambda t: len(t.script))
        row = asyncio.run(run_bench.episode(task, run_bench.ARMS["agree"], Scripted(task)))
        self.assertEqual(row["resolved"], {"agreed": len(task.script)})

    def test_dry_run_handles_the_multi_suite(self):
        with tempfile.TemporaryDirectory() as folder:
            args = run_bench.parse(["--dry-run", "--suites", "multi", "--tasks", "10",
                                    "--arms", "plain,think,escalate,carry", "--out", folder])

            def make_client(items):
                from clients import SimulatedModel
                return SimulatedModel({task.question: task for task in items}, seed=1)
            details = {}
            table = asyncio.run(run_bench.run(args, make_client, details))
        self.assertEqual([row["arm"] for row in table], args.arms)
        self.assertGreater(table[0]["calls_per_task"], 4)
        self.assertTrue(all("steps" in row for row in details["multi"]["carry"]))


class GateTests(unittest.TestCase):
    def gate(self, state, typed="", **kwargs):
        said = []
        allowed = gate.confirm_live("http://x/v1", "model-a", 100, 1, ask=lambda _: typed,
                                    say=said.append, probe=lambda *a: state, **kwargs)
        return allowed, "\n".join(said)

    LOADED = {"reachable": True, "listed": True, "loaded": True, "loaded_models": ["model-a"], "note": ""}
    OTHER = {"reachable": True, "listed": True, "loaded": False, "loaded_models": ["model-b"], "note": ""}
    UNKNOWN = {"reachable": True, "listed": None, "loaded": None, "note": "HTTP 401"}
    DOWN = {"reachable": False, "listed": None, "loaded": None, "note": "refused"}

    def test_loaded_model_needs_the_name_typed_back(self):
        allowed, text = self.gate(self.LOADED, typed="model-a")
        self.assertTrue(allowed)
        self.assertIn("already loaded", text)
        self.assertIn("prompt cache", text)
        self.assertFalse(self.gate(self.LOADED, typed="yes")[0])
        self.assertFalse(self.gate(self.LOADED, typed="")[0])

    def test_refuses_a_model_swap_unless_allowed(self):
        allowed, text = self.gate(self.OTHER, typed="model-a")
        self.assertFalse(allowed)
        self.assertIn("model-b", text)
        self.assertTrue(self.gate(self.OTHER, typed="model-a", allow_model_swap=True)[0])

    def test_refuses_when_state_is_unknown_or_server_is_down(self):
        self.assertFalse(self.gate(self.UNKNOWN, typed="model-a")[0])
        self.assertTrue(self.gate(self.UNKNOWN, typed="model-a", allow_unknown_state=True)[0])
        self.assertFalse(self.gate(self.DOWN, typed="model-a", allow_unknown_state=True,
                                   allow_model_swap=True, assume_yes=True)[0])

    def test_a_sleeping_model_may_be_woken_only_when_nothing_else_is_held(self):
        asleep = {"reachable": True, "listed": True, "loaded": False, "loaded_models": [],
                  "sleeping_models": ["model-a"], "asleep": True, "note": ""}
        allowed, text = self.gate(asleep, typed="model-a")
        self.assertTrue(allowed)
        self.assertIn("asleep", text)
        other_asleep = dict(asleep, sleeping_models=["model-b"], asleep=False)
        allowed, text = self.gate(other_asleep, typed="model-a")
        self.assertFalse(allowed)
        self.assertIn("model-b", text)
        both = dict(asleep, loaded_models=["model-b"])
        self.assertFalse(self.gate(both, typed="model-a")[0])

    def test_an_idle_server_may_load_the_model_because_nothing_is_displaced(self):
        idle = {"reachable": True, "listed": True, "loaded": False, "loaded_models": [],
                "sleeping_models": [], "asleep": False, "note": ""}
        allowed, text = self.gate(idle, typed="model-a")
        self.assertTrue(allowed)
        self.assertIn("nothing is", text)
        self.assertFalse(self.gate(idle, typed="no")[0])

    def test_router_status_reply_is_understood(self):
        idle = {"state": "unloaded", "model": None, "queued": 0, "active": False,
                "models": [{"id": "a", "loaded": False}, {"id": "b", "loaded": False}]}
        self.assertEqual(gate.from_status(idle), ([], False))
        working = {"state": "loaded", "model": "b", "queued": 1, "active": True,
                   "models": [{"id": "a", "loaded": False}, {"id": "b", "loaded": True}]}
        self.assertEqual(gate.from_status(working), (["b"], True))
        loading = dict(working, state="loading", models=[{"id": "a", "loaded": False},
                                                         {"id": "b", "loaded": False}])
        self.assertEqual(gate.from_status(loading)[0], ["b"])
        self.assertIsNone(gate.from_status({"status": "ok"}))
        self.assertIsNone(gate.from_status({"models": [{"id": "a"}]}))

    def test_a_busy_server_is_called_out(self):
        busy = dict(self.LOADED, busy=True)
        allowed, text = self.gate(busy, typed="model-a")
        self.assertTrue(allowed)
        self.assertIn("in use now", text)

    def test_yes_skips_only_the_typing_not_the_safety_checks(self):
        self.assertTrue(self.gate(self.LOADED, assume_yes=True)[0])
        self.assertFalse(self.gate(self.OTHER, assume_yes=True)[0])


if __name__ == "__main__":
    unittest.main()
