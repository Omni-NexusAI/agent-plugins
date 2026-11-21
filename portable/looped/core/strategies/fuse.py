"""Merge two drafts of a final answer (same model, aggregator pass).

Only for open-ended final text. Short answers are settled by voting instead,
and tool calls are never merged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..canonical import final_text
from ..prompts import FUSE
from ..types import Candidate, Decision

if TYPE_CHECKING:
    from ..pipeline import StepContext


def applies(first: Candidate, second: Candidate, cfg: dict[str, Any]) -> bool:
    settings = cfg["strategies"]["fuse"]
    if not settings["enabled"] or first.kind != "final" or second.kind != "final":
        return False
    shortest = min(len(final_text(first.tool_args)), len(final_text(second.tool_args)))
    return shortest >= settings["min_chars"]


async def run(first: Candidate, second: Candidate, ctx: "StepContext",
              decision: Decision) -> Candidate | None:
    prompt = FUSE.format(first=final_text(first.tool_args),
                         second=final_text(second.tool_args),
                         tool=first.tool_name)
    return await ctx.extra_ask(prompt, "F", decision)
