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


class EscalateTests(unittest.TestCase):
    SETTINGS = {"mode": "always", "strategies": {"escalate": {"enabled": True}}}

    def resolve(self, first, model, settings=None, **kwargs):
        ctx = context(model, settings or self.SETTINGS, think=model.think, **kwargs)
        return run(resolve_step(first, "", 0, ctx))

    def test_agreeing_quick_passes_do_not_reason(self):
        a = step("write", path="a")
        model = FakeModel(samples=[a])
        decision = self.resolve(a, model)
        self.assertEqual((decision.strategy, decision.outcome, decision.extra_calls),
                         ("escalate", "agreed", 1))
        self.assertEqual(model.think_calls, 0)

    def test_disagreement_is_settled_by_the_reasoned_pass(self):
        a, b, c = step("write", path="a"), step("write", path="b"), step("write", path="c")
        model = FakeModel(samples=[b], thinks=[c])
        decision = self.resolve(a, model)
        self.assertEqual((decision.outcome, decision.winner.label, decision.extra_calls),
                         ("reasoned", "T", 2))
        self.assertEqual(model.sample_calls, [1])            # no third quick sample
        model = FakeModel(samples=[b], thinks=[a])
        decision = self.resolve(a, model)
        self.assertEqual((decision.outcome, decision.winner.label), ("reasoned_same", "A"))
        self.assertFalse(decision.changed)

    def test_an_unusable_quick_pass_also_triggers_reasoning(self):
        a, c = step("write", path="a"), step("write", path="c")
        decision = self.resolve("junk", FakeModel(samples=[a], thinks=[c]))
        self.assertEqual((decision.outcome, decision.winner.label), ("reasoned", "T"))
        decision = self.resolve(a, FakeModel(samples=["junk"], thinks=[c]))
        self.assertEqual((decision.outcome, decision.winner.label), ("reasoned", "T"))

    def test_an_unusable_reasoned_pass_keeps_the_best_quick_one(self):
        a, b = step("write", path="a"), step("write", path="b")
        decision = self.resolve(a, FakeModel(samples=[b], thinks=["junk"]))
        self.assertEqual((decision.outcome, decision.winner.label), ("reasoning_unusable", "A"))
        decision = self.resolve("junk", FakeModel(samples=[b], thinks=[RuntimeError("down")]))
        self.assertEqual((decision.outcome, decision.winner.label), ("reasoning_unusable", "B"))

    def test_no_budget_means_no_reasoning(self):
        a, b = step("write", path="a"), step("write", path="b")
        settings = {"mode": "always", "budget": {"allow_tiebreak": False},
                    "strategies": {"escalate": {"enabled": True}}}
        model = FakeModel(samples=[b])
        decision = self.resolve(a, model, settings)
        self.assertEqual((decision.outcome, decision.winner.label, model.think_calls),
                         ("unsure_no_budget", "A", 0))

    def test_long_final_answers_are_merged_not_reasoned(self):
        model = FakeModel(samples=[final(LONG_B)], asks=[final("merged")], thinks=[final("x")])
        decision = self.resolve(final(LONG_A), model)
        self.assertEqual((decision.outcome, model.think_calls), ("fused", 0))

    def test_a_host_that_cannot_reason_falls_back_to_agreement(self):
        a, b = step("write", path="a"), step("write", path="b")
        model = FakeModel(samples=[b, b])
        decision = run(resolve_step(a, "", 0, context(model, self.SETTINGS)))
        self.assertEqual((decision.strategy, decision.outcome, decision.winner.label),
                         ("agree", "tiebreak", "B"))

    def test_reasoning_starts_from_scratch_unless_passes_are_carried(self):
        a, b, c = step("write", path="a"), step("write", path="b"), step("write", path="c")
        model = FakeModel(samples=[b], thinks=[c])
        self.resolve(a, model)
        self.assertEqual(model.think_notes, [None])


class CarryTests(unittest.TestCase):
    SETTINGS = {"mode": "always", "budget": {"max_extra_calls_per_turn": 8},
                "strategies": {"escalate": {"enabled": True, "carry": True}}}

    def resolve(self, first, model, settings=None, **kwargs):
        ctx = context(model, settings or self.SETTINGS, think=model.think, **kwargs)
        return run(resolve_step(first, "", 0, ctx))

    def test_the_reasoning_call_is_shown_both_quick_attempts(self):
        a, b, c = step("write", path="a"), step("write", path="b"), step("write", path="c")
        model = FakeModel(samples=[b], thinks=[c])
        decision = self.resolve(a, model)
        self.assertEqual((decision.outcome, decision.winner.label, decision.extra_calls),
                         ("reasoned", "T", 2))
        note = model.think_notes[0]
        self.assertIn(a, note)
        self.assertIn(b, note)
        self.assertLess(note.index(a), note.index(b))
        self.assertEqual(model.ask_calls, [])

    def test_an_unusable_attempt_is_named_as_such_and_long_ones_are_shortened(self):
        a, c = step("write", path="a"), step("write", path="c")
        model = FakeModel(samples=[""], thinks=[c])
        self.resolve(a, model)
        self.assertIn("(no usable reply)", model.think_notes[0])
        long_step = step("write", path="p" * 5000)
        model = FakeModel(samples=[a], thinks=[c])
        self.resolve(long_step, model)
        self.assertLess(len(model.think_notes[0]), 3500)

    def test_agreeing_quick_passes_still_do_not_reason(self):
        a = step("write", path="a")
        model = FakeModel(samples=[a])
        decision = self.resolve(a, model)
        self.assertEqual((decision.outcome, model.think_calls), ("agreed", 0))

    def test_reasoning_that_ran_out_of_room_hands_its_notes_to_a_quick_call(self):
        a, b, c = step("write", path="a"), step("write", path="b"), step("write", path="c")
        model = FakeModel(samples=[b], thinks=[""], asks=[c])      # think() reports reasoning text
        decision = self.resolve(a, model)
        self.assertEqual((decision.outcome, decision.winner.label, decision.extra_calls),
                         ("rescued", "R", 3))
        self.assertIn("reasoned", model.ask_calls[0])              # the notes are in the quick call
        self.assertIn("Do not start over", model.ask_calls[0])
        model = FakeModel(samples=[b], thinks=[""], asks=[a])
        decision = self.resolve(a, model)
        self.assertEqual((decision.outcome, decision.winner.label), ("rescued_same", "A"))
        self.assertFalse(decision.changed)

    def test_a_failed_rescue_keeps_the_best_quick_pass(self):
        a, b = step("write", path="a"), step("write", path="b")
        model = FakeModel(samples=[b], thinks=[""], asks=["junk"])
        decision = self.resolve(a, model)
        self.assertEqual((decision.outcome, decision.winner.label), ("reasoning_unusable", "A"))
        model = FakeModel(samples=[b], thinks=[""], asks=[RuntimeError("down")])
        decision = self.resolve("junk", model)
        self.assertEqual((decision.outcome, decision.winner.label), ("reasoning_unusable", "B"))

    def test_no_rescue_without_budget_or_when_the_reasoning_call_failed(self):
        a, b = step("write", path="a"), step("write", path="b")
        settings = {"mode": "always", "budget": {"max_extra_calls_per_turn": 2},
                    "strategies": {"escalate": {"enabled": True, "carry": True}}}
        model = FakeModel(samples=[b], thinks=[""])
        decision = self.resolve(a, model, settings)
        self.assertEqual((decision.outcome, model.ask_calls), ("reasoning_unusable", []))
        model = FakeModel(samples=[b], thinks=[RuntimeError("down")])
        decision = self.resolve(a, model)
        self.assertEqual((decision.outcome, model.ask_calls), ("reasoning_unusable", []))

    def test_long_notes_keep_their_start_and_end(self):
        from core.strategies.escalate import notes_note
        text = "START" + "x" * 20000 + "END"
        note = notes_note(text)
        self.assertIn("START", note)
        self.assertIn("END", note)
        self.assertLess(len(note), 7000)


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
