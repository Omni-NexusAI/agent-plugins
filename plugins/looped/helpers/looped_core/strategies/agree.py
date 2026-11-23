"""Agreement gate: a second sample must propose the same step.

Self-consistency restricted to discrete decisions. A tool call is never
synthesised from two candidates; the winner is always one whole candidate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..types import Candidate, Decision
from . import fuse

if TYPE_CHECKING:
    from ..pipeline import StepContext


async def resolve(first: Candidate, ctx: "StepContext", reason: str) -> Decision:
    decision = Decision(winner=first, strategy="agree", reason=reason, candidates=[first])
    second = await ctx.extra_sample(1, "B", decision)
    if second is None:
        decision.outcome = "second_unavailable"
        return decision

    if not second.valid:
        decision.outcome = "both_invalid" if not first.valid else "second_invalid"
        return decision
    if not first.valid:
        decision.winner, decision.outcome = second, "only_valid"
        return decision
    if first.key == second.key:
        decision.outcome = "agreed"
        return decision

    budget = ctx.cfg["budget"]
    if not budget["allow_tiebreak"] or ctx.state.remaining(ctx.cfg) - decision.extra_calls <= 0:
        decision.outcome = "disagreed_kept_first"
        return decision

    if fuse.applies(first, second, ctx.cfg):
        fused = await fuse.run(first, second, ctx, decision)
        if fused is not None and fused.kind == "final":
            decision.winner, decision.outcome = fused, "fused"
        else:
            decision.outcome = "fuse_failed"
        return decision

    third = await ctx.extra_sample(2, "C", decision)
    if third is not None and third.valid and third.key == first.key:
        decision.outcome = "tiebreak"
    elif third is not None and third.valid and third.key == second.key:
        decision.winner, decision.outcome = second, "tiebreak"
    else:
        decision.outcome = "no_majority"
    return decision
