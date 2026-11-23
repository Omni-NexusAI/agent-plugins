"""Think when unsure: reason only about the steps two quick samples disagree on.

Experimental. Two quick samples that do not propose the same step, or an
unusable one, are a cheap sign that the step is uncertain. Only then is the
prompt asked once more with the model's reasoning switched on, and that
candidate wins when it is a valid step. Steps the quick samples agree on cost
one extra quick call and no reasoning.

With ``carry`` on, a later pass builds on the earlier ones instead of starting
from scratch: the reasoning call is shown the two quick attempts, and a
reasoning call that runs out of room hands its notes to one quick call that
answers from them. Every pass still starts from the unchanged prompt; the
earlier work is added as a note.

A host that cannot switch reasoning on supplies no ``think`` call, and this
falls back to the agreement gate. The winner is always one whole candidate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..prompts import CARRY_NOTES, CARRY_PASSES, UNUSABLE_ATTEMPT
from ..types import Candidate, Decision
from . import agree, fuse

if TYPE_CHECKING:
    from ..pipeline import StepContext

ATTEMPT_CHARS = 2000            # of each quick attempt shown to the reasoning call
NOTES_HEAD, NOTES_TAIL = 1500, 4500     # of cut-off reasoning handed to the quick call


def _attempt(candidate: Candidate | None) -> str:
    if candidate is None or not str(candidate.raw or "").strip():
        return UNUSABLE_ATTEMPT
    return str(candidate.raw).strip()[:ATTEMPT_CHARS]


def passes_note(first: Candidate, second: Candidate | None) -> str:
    return CARRY_PASSES.format(first=_attempt(first), second=_attempt(second))


def notes_note(reasoning: str) -> str:
    text = reasoning.strip()
    if len(text) > NOTES_HEAD + NOTES_TAIL:
        text = text[:NOTES_HEAD] + "\n[...]\n" + text[-NOTES_TAIL:]
    return CARRY_NOTES.format(notes=text)


async def resolve(first: Candidate, ctx: "StepContext", reason: str) -> Decision:
    if ctx.think is None:
        return await agree.resolve(first, ctx, reason)
    decision = Decision(winner=first, strategy="escalate", reason=reason, candidates=[first])
    second = await ctx.extra_sample(1, "B", decision)
    second_ok = second is not None and second.valid
    if first.valid and second_ok and first.key == second.key:
        decision.outcome = "agreed"
        return decision

    # Without the reasoning pass the best quick candidate stands.
    if not first.valid and second_ok:
        decision.winner = second
    budget = ctx.cfg["budget"]
    if not budget["allow_tiebreak"] or ctx.state.remaining(ctx.cfg) - decision.extra_calls <= 0:
        decision.outcome = "unsure_no_budget"
        return decision

    if first.valid and second_ok and fuse.applies(first, second, ctx.cfg):
        # Two long final answers rarely match word for word; merging suits them better.
        fused = await fuse.run(first, second, ctx, decision)
        if fused is not None and fused.kind == "final":
            decision.winner, decision.outcome = fused, "fused"
        else:
            decision.outcome = "fuse_failed"
        return decision

    carry = ctx.cfg["strategies"]["escalate"]["carry"]
    careful = await ctx.extra_think("T", decision, passes_note(first, second) if carry else None)
    rescued = False
    if (carry and careful is not None and not careful.valid
            and str(careful.reasoning or "").strip()
            and ctx.state.remaining(ctx.cfg) - decision.extra_calls > 0):
        # The reasoning never reached a step. Its notes are not thrown away:
        # one quick call answers from them.
        careful = await ctx.extra_ask(notes_note(str(careful.reasoning)), "R", decision)
        rescued = True
    if careful is None or not careful.valid:
        decision.outcome = "reasoning_unusable"
    elif first.valid and careful.key == first.key:
        decision.winner = first
        decision.outcome = "rescued_same" if rescued else "reasoned_same"
    else:
        decision.winner = careful
        decision.outcome = "rescued" if rescued else "reasoned"
    return decision
