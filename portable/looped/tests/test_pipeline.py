import asyncio
import unittest

import support  # noqa: F401
from core import Metrics, TurnState, resolve_step
from support import FakeModel, context, final, run, step

ALWAYS = {"mode": "always"}
LONG_A = "First draft. " * 40
LONG_B = "Second draft. " * 40


class PassThroughTests(unittest.TestCase):
    def test_inactive_mode_makes_no_extra_calls(self):
        model = FakeModel()
        decision = run(resolve_step(step("code_execution_tool", code="x"), "", 0, context(model)))
        self.assertEqual((decision.strategy, decision.extra_calls, model.calls), ("none", 0, 0))
        self.assertFalse(decision.changed)

    def test_auto_skips_ordinary_steps(self):
        model = FakeModel()
        decision = run(resolve_step(step("search_engine", query="x"), "", 2,
                                    context(model, {"mode": "auto"})))
        self.assertEqual((decision.strategy, model.calls), ("none", 0))

    def test_no_step_strategy_enabled_passes_through(self):
        model = FakeModel()
        settings = {"mode": "always", "strategies": {"agree": {"enabled": False}}}
        decision = run(resolve_step(step("a", x=1), "", 0, context(model, settings)))
        self.assertEqual((decision.strategy, model.calls), ("none", 0))


class AgreeTests(unittest.TestCase):
    def resolve(self, first, model, settings=ALWAYS, **kwargs):
        ctx = context(model, settings, **kwargs)
        return run(resolve_step(first, "", 0, ctx)), ctx

    def test_agreement_commits_the_first_candidate_with_one_extra_call(self):
        model = FakeModel(samples=[step("write", path="a.txt", text="x ")])
        decision, ctx = self.resolve(step("write", text="x", path="a.txt"), model)
        self.assertEqual((decision.outcome, decision.winner.label, decision.extra_calls),
                         ("agreed", "A", 1))
        self.assertEqual((model.sample_calls, ctx.state.extra_calls), ([1], 1))

    def test_disagreement_is_settled_by_a_third_sample(self):
        a, b = step("write", path="a.txt"), step("write", path="b.txt")
        model = FakeModel(samples=[b, b])
        decision, _ = self.resolve(a, model)
        self.assertEqual((decision.outcome, decision.winner.label, decision.extra_calls),
                         ("tiebreak", "B", 2))
        self.assertTrue(decision.changed)
        self.assertEqual(model.sample_calls, [1, 2])

        decision, _ = self.resolve(a, FakeModel(samples=[b, a]))
        self.assertEqual((decision.outcome, decision.winner.label), ("tiebreak", "A"))

    def test_three_way_split_keeps_the_first_candidate(self):
        model = FakeModel(samples=[step("write", path="b"), step("write", path="c")])
        decision, _ = self.resolve(step("write", path="a"), model)
        self.assertEqual((decision.outcome, decision.winner.label), ("no_majority", "A"))

    def test_tiebreak_can_be_disabled(self):
        model = FakeModel(samples=[step("write", path="b")])
        settings = {"mode": "always", "budget": {"allow_tiebreak": False}}
        decision, _ = self.resolve(step("write", path="a"), model, settings)
        self.assertEqual((decision.outcome, decision.extra_calls), ("disagreed_kept_first", 1))

    def test_invalid_first_candidate_is_replaced_by_a_valid_second(self):
        model = FakeModel(samples=[step("search", q="x")])
        decision, _ = self.resolve("not json at all", model)
        self.assertEqual((decision.outcome, decision.winner.label), ("only_valid", "B"))

    def test_invalid_second_candidate_never_wins(self):
        decision, _ = self.resolve(step("search", q="x"), FakeModel(samples=["junk"]))
        self.assertEqual((decision.outcome, decision.winner.label), ("second_invalid", "A"))
        decision, _ = self.resolve("junk", FakeModel(samples=["junk too"]))
        self.assertEqual((decision.outcome, decision.winner.label), ("both_invalid", "A"))

    def test_unknown_tool_loses_to_a_known_one(self):
        model = FakeModel(samples=[step("search", q="x")])
        decision, _ = self.resolve(step("serach", q="x"), model, tool_names=["search", "response"])
        self.assertEqual((decision.outcome, decision.winner.tool_name), ("only_valid", "search"))

    def test_model_failure_falls_back_to_the_first_candidate(self):
        decision, _ = self.resolve(step("a", x=1), FakeModel(samples=[RuntimeError("down")]))
        self.assertEqual((decision.outcome, decision.winner.label), ("second_unavailable", "A"))

    def test_short_final_answers_are_voted_not_fused(self):
        model = FakeModel(samples=[final("41"), final(" 42. ")])
        decision, _ = self.resolve(final("42"), model)
        self.assertEqual((decision.outcome, decision.winner.label), ("tiebreak", "A"))
        self.assertEqual(model.ask_calls, [])

    def test_long_final_answers_are_fused(self):
        model = FakeModel(samples=[final(LONG_B)], asks=[final("Merged answer.")])
        decision, _ = self.resolve(final(LONG_A), model)
        self.assertEqual((decision.outcome, decision.winner.label, decision.extra_calls),
                         ("fused", "F", 2))
        self.assertEqual(decision.winner.tool_args["text"], "Merged answer.")
        self.assertIn("Draft 1:", model.ask_calls[0])

    def test_a_fuse_that_returns_a_tool_call_is_rejected(self):
        model = FakeModel(samples=[final(LONG_B)], asks=[step("code_execution_tool", code="x")])
        decision, _ = self.resolve(final(LONG_A), model)
        self.assertEqual((decision.outcome, decision.winner.label), ("fuse_failed", "A"))

    def test_final_versus_action_is_never_fused(self):
        model = FakeModel(samples=[step("search", q="x"), step("search", q="x")])
        decision, _ = self.resolve(final(LONG_A), model)
        self.assertEqual((decision.outcome, decision.winner.label), ("tiebreak", "B"))
        self.assertEqual(model.ask_calls, [])

    def test_turn_budget_blocks_the_tiebreak(self):
        model = FakeModel(samples=[step("write", path="b")])
        settings = {"mode": "always", "budget": {"max_extra_calls_per_turn": 3}}
        decision, ctx = self.resolve(step("write", path="a"), model, settings,
                                     state=TurnState(extra_calls=2))
        self.assertEqual((decision.outcome, model.calls), ("disagreed_kept_first", 1))
        self.assertEqual(ctx.state.extra_calls, 3)

    def test_retry_arm_is_consumed_by_the_next_checked_step(self):
        model = FakeModel(samples=[step("search", q="x")])
        state = TurnState(retry_armed=True)
        ctx = context(model, {"mode": "auto"}, state=state)
        decision = run(resolve_step(step("search", q="x"), "", 4, ctx))
        self.assertEqual(decision.reason, "after_error")
        self.assertEqual((state.retry_armed, state.retries_used), (False, 1))

    def test_trace_contains_no_prompt_or_argument_text(self):
        model = FakeModel(samples=[step("write", path="secret-b.txt")] * 2)
        decision, _ = self.resolve(step("write", path="secret-a.txt"), model)
        trace = repr(decision.trace())
        self.assertNotIn("secret", trace)
        self.assertIn("'tool': 'write'", trace)


class EarlySecondTests(unittest.TestCase):
    def test_a_second_sample_started_early_is_reused(self):
        async def scenario():
            model = FakeModel()

            async def early():
                return step("a", x=1), ""
            ctx = context(model, ALWAYS, early_second=asyncio.ensure_future(early()))
            return await resolve_step(step("a", x=1), "", 0, ctx), model
        decision, model = run(scenario())
        self.assertEqual((decision.outcome, decision.extra_calls, model.calls), ("agreed", 1, 0))

    def test_an_unneeded_early_sample_is_cancelled(self):
        async def scenario():
            async def early():
                await asyncio.sleep(30)
                return "", ""
            task = asyncio.ensure_future(early())
            ctx = context(FakeModel(), {"mode": "auto"}, early_second=task)
            decision = await resolve_step(step("search_engine", query="x"), "", 3, ctx)
            await asyncio.sleep(0)
            return decision, task
        decision, task = run(scenario())
        self.assertEqual(decision.strategy, "none")
        self.assertTrue(task.cancelled())


class DeepenTests(unittest.TestCase):
    SETTINGS = {"mode": "always", "strategies": {"deepen": {"enabled": True}}}

    def test_second_pass_sees_the_draft_and_can_revise_it(self):
        draft, revised = step("write", path="a"), step("write", path="b")
        model = FakeModel(asks=[revised])
        decision = run(resolve_step(draft, "", 0, context(model, self.SETTINGS)))
        self.assertEqual((decision.strategy, decision.outcome, decision.winner.label),
                         ("deepen", "revised", "D"))
        self.assertIn(draft, model.ask_calls[0])
        self.assertEqual(model.sample_calls, [])

    def test_confirmed_or_invalid_second_pass_keeps_the_draft(self):
        draft = step("write", path="a")
        decision = run(resolve_step(draft, "", 0, context(FakeModel(asks=[draft]), self.SETTINGS)))
        self.assertEqual((decision.outcome, decision.winner.label), ("confirmed", "A"))
        decision = run(resolve_step(draft, "", 0, context(FakeModel(asks=["junk"]), self.SETTINGS)))
        self.assertEqual((decision.outcome, decision.winner.label), ("second_invalid", "A"))


class MetricsTests(unittest.TestCase):
    def test_counts_checked_steps_and_cost(self):
        metrics = Metrics()
        a, b = step("write", path="a"), step("write", path="b")
        for first, samples in ((a, [a]), (a, [b, b])):
            metrics.record(run(resolve_step(first, "", 0, context(FakeModel(samples=samples), ALWAYS))))
        metrics.record(run(resolve_step(a, "", 0, context(FakeModel()))))
        report = metrics.to_dict()
        self.assertEqual((report["steps"], report["checked"], report["extra_calls"],
                          report["changed"]), (3, 2, 3, 1))
        self.assertEqual(report["calls_per_step"], 2.0)
        self.assertEqual(report["outcomes"], {"agreed": 1, "tiebreak": 1})


if __name__ == "__main__":
    unittest.main()
