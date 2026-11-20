"""Reason twice: draft a step, then re-answer with the draft in view.

Experimental. The literature rates plain re-answering as weak on small models
(the second pass tends to anchor on the first), so this ships disabled and is
there to be measured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..prompts import DEEPEN
from ..types import Candidate, Decision

if TYPE_CHECKING:
    from ..pipeline import StepContext


async def resolve(first: Candidate, ctx: "StepContext", reason: str) -> Decision:
    decision = Decision(winner=first, strategy="deepen", reason=reason, candidates=[first])
    second = await ctx.extra_ask(DEEPEN.format(draft=first.raw), "D", decision)
    if second is None:
        decision.outcome = "second_unavailable"
    elif not second.valid:
        decision.outcome = "second_invalid"
    elif first.valid and second.key == first.key:
        decision.outcome = "confirmed"
    else:
        decision.winner, decision.outcome = second, "revised"
    return decision
