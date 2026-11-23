import unittest

import support  # noqa: F401
from core import TurnState, merge_config
from core.strategies import plan_branch, reread, retry
from support import run


class RereadTests(unittest.TestCase):
    def test_repeats_the_task_once(self):
        block = reread.build("Sum 2 and 3.", merge_config())
        self.assertEqual(block.count("Sum 2 and 3."), 1)
        self.assertTrue(block.startswith("Read the task again"))

    def test_skipped_for_thinking_models_unless_forced(self):
        self.assertIsNone(reread.build("task", merge_config(), thinking=True))
        forced = merge_config({"strategies": {"reread": {"when": "always"}}})
        self.assertIsNotNone(reread.build("task", forced, thinking=True))

    def test_skipped_when_off_empty_or_oversized(self):
        off = merge_config({"strategies": {"reread": {"enabled": False}}})
        never = merge_config({"strategies": {"reread": {"when": "never"}}})
        small = merge_config({"strategies": {"reread": {"max_chars": 5}}})
        self.assertIsNone(reread.build("task", off))
        self.assertIsNone(reread.build("task", never))
        self.assertIsNone(reread.build("   ", merge_config()))
        self.assertIsNone(reread.build(None, merge_config()))
        self.assertIsNone(reread.build("a task longer than five", small))


class RetryTests(unittest.TestCase):
    def test_recognises_real_failures_only(self):
        for text in ("Traceback (most recent call last):\n  File x", "bash: foo: command not found",
                     "ValueError: bad input", "Error: file missing", "Process exited with code 2",
                     "cat: a.txt: No such file or directory", "Tool frobnicate not found"):
            self.assertTrue(retry.looks_like_error(text), text)
        for text in ("42", "Wrote 3 files.", "No errors were found in the log.",
                     "exit code: 0", None, 17):
            self.assertFalse(retry.looks_like_error(text), text)

    def test_arms_until_the_per_turn_cap(self):
        cfg, state = merge_config(), TurnState()
        self.assertTrue(retry.note_tool_result("Error: boom", cfg, state))
        self.assertTrue(state.retry_armed)
        state = TurnState(retries_used=2)
        self.assertFalse(retry.note_tool_result("Error: boom", cfg, state))
        self.assertFalse(state.retry_armed)

    def test_host_verdict_overrides_the_text_heuristic(self):
        cfg = merge_config()
        state = TurnState()
        self.assertTrue(retry.note_tool_result("all good", cfg, state, failed=True))
        state = TurnState()
        self.assertFalse(retry.note_tool_result("Error: looks bad", cfg, state, failed=False))
        self.assertFalse(state.retry_armed)

    def test_disabled_strategy_never_arms(self):
        cfg = merge_config({"strategies": {"retry": {"enabled": False}}})
        state = TurnState()
        self.assertFalse(retry.note_tool_result("Error: boom", cfg, state))
        self.assertFalse(state.retry_armed)


class PlanBranchTests(unittest.TestCase):
    ON = {"strategies": {"plan_branch": {"enabled": True}}}

    def planner(self, replies):
        calls = []

        async def plain(system, user, variant):
            calls.append((system, user, variant))
            reply = replies[len(calls) - 1]
            if isinstance(reply, Exception):
                raise reply
            return reply
        return plain, calls

    def test_disabled_by_default(self):
        plain, calls = self.planner([])
        self.assertIsNone(run(plan_branch.build("task", plain, merge_config(), TurnState())))
        self.assertEqual(calls, [])

    def test_two_drafts_are_merged_into_one_note(self):
        plain, calls = self.planner(["1. a", "1. b", "1. merged"])
        state = TurnState()
        note = run(plan_branch.build("Build it", plain, merge_config(self.ON), state))
        self.assertIn("1. merged", note)
        self.assertEqual([variant for _, _, variant in calls], [1, 2, 0])
        self.assertIn("Plan 1:\n1. a", calls[2][1])
        self.assertIn("do not call tools", calls[0][0].lower())
        self.assertEqual((state.extra_calls, state.plan_done), (3, True))

    def test_runs_once_per_turn(self):
        plain, calls = self.planner(["1. a", "1. b", "1. merged"])
        state = TurnState()
        cfg = merge_config(self.ON)
        run(plan_branch.build("Build it", plain, cfg, state))
        self.assertIsNone(run(plan_branch.build("Build it", plain, cfg, state)))
        self.assertEqual(len(calls), 3)

    def test_survives_a_failed_branch_and_a_failed_merge(self):
        plain, _ = self.planner([RuntimeError("down"), "1. only"])
        note = run(plan_branch.build("t", plain, merge_config(self.ON), TurnState()))
        self.assertIn("1. only", note)
        plain, _ = self.planner(["1. a", "1. b", RuntimeError("down")])
        note = run(plan_branch.build("t", plain, merge_config(self.ON), TurnState()))
        self.assertIn("1. a", note)
        plain, _ = self.planner([RuntimeError("x"), RuntimeError("y")])
        self.assertIsNone(run(plan_branch.build("t", plain, merge_config(self.ON), TurnState())))

    def test_respects_the_turn_budget_and_length_cap(self):
        plain, calls = self.planner([])
        cfg = merge_config({**self.ON, "budget": {"max_extra_calls_per_turn": 1}})
        self.assertIsNone(run(plan_branch.build("t", plain, cfg, TurnState())))
        self.assertEqual(calls, [])
        plain, _ = self.planner(["x" * 5000, "y", "z" * 5000])
        cfg = merge_config({"strategies": {"plan_branch": {"enabled": True, "max_chars": 300}}})
        note = run(plan_branch.build("t", plain, cfg, TurnState()))
        self.assertLessEqual(note.count("z"), 300)


if __name__ == "__main__":
    unittest.main()
