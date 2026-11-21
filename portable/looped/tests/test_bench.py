import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401

BENCH = Path(__file__).resolve().parents[1] / "bench"
sys.path.insert(0, str(BENCH))

import gate  # noqa: E402
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
                         {(suite, arm) for suite in ("arith", "tool") for arm in run_bench.ARMS})
        by_arm = {(row["suite"], row["arm"]): row for row in table}
        self.assertEqual(by_arm[("tool", "plain")]["calls_per_task"], 1.0)
        self.assertEqual(by_arm[("tool", "reread")]["calls_per_task"], 1.0)
        self.assertGreater(by_arm[("tool", "agree")]["calls_per_task"], 2.0)
        self.assertEqual(by_arm[("tool", "deepen")]["calls_per_task"], 2.0)
        self.assertIn("fixed", by_arm[("arith", "agree")])
        self.assertIn("| arith | agree |", run_bench.markdown(table, "t"))

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
