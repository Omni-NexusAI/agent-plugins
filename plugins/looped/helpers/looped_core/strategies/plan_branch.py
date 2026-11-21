"""Parallel planning: independent plans, merged once, executed once.

Experimental. Branches only write text, so no tool runs twice. The merged plan
is handed to the host as guidance for the single real execution.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from ..controller import TurnState
from ..prompts import PLAN_MERGE_SYSTEM, PLAN_NOTE, PLAN_SYSTEM

Plain = Callable[[str, str, int], Awaitable[str]]


async def build(task: str, plain: Plain, cfg: dict[str, Any],
                state: TurnState) -> str | None:
    """Return a guidance note, or ``None`` when planning is off or fails."""
    settings = cfg["strategies"]["plan_branch"]
    task = task.strip() if isinstance(task, str) else ""
    if not settings["enabled"] or state.plan_done or not task:
        return None
    branches = min(settings["branches"], state.remaining(cfg))
    if branches < 2:
        return None
    state.plan_done = True
    state.extra_calls += branches
    results = await asyncio.gather(
        *(plain(PLAN_SYSTEM, task, index + 1) for index in range(branches)),
        return_exceptions=True)
    drafts = [item.strip() for item in results if isinstance(item, str) and item.strip()]
    if not drafts:
        return None
    plan = drafts[0]
    if len(drafts) > 1 and state.remaining(cfg) > 0:
        state.extra_calls += 1
        listing = "\n\n".join(f"Plan {index + 1}:\n{draft}"
                              for index, draft in enumerate(drafts))
        try:
            merged = await plain(PLAN_MERGE_SYSTEM, f"Task:\n{task}\n\n{listing}", 0)
        except Exception:
            merged = ""
        if isinstance(merged, str) and merged.strip():
            plan = merged.strip()
    return PLAN_NOTE.format(plan=plan[:settings["max_chars"]])
