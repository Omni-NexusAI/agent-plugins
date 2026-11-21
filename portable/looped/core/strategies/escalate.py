"""Think when unsure: reason only about the steps two quick samples disagree on.

Experimental. Two quick samples that do not propose the same step, or an
unusable one, are a cheap sign that the step is uncertain. Only then is the
unchanged prompt asked once more with the model's reasoning switched on, and
that candidate wins when it is a valid step. Steps the quick samples agree on
cost one extra quick call and no reasoning.

A host that cannot switch reasoning on supplies no ``think`` call, and this
falls back to the agreement gate. The winner is always one whole candidate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..types import Candidate, Decision
from . import agree, fuse

if TYPE_CHECKING:
    from ..pipeline import StepContext


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

    careful = await ctx.extra_think("T", decision)
    if careful is None or not careful.valid:
        decision.outcome = "reasoning_unusable"
    elif first.valid and careful.key == first.key:
        decision.winner, decision.outcome = first, "reasoned_same"
    else:
        decision.winner, decision.outcome = careful, "reasoned"
    return decision
