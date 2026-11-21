"""Resolve one agent step: pass it through, or look twice and pick a winner."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from .canonical import FINAL_TOOLS, build_candidate
from .controller import TurnState, checkpoint
from .strategies import agree, deepen, escalate
from .types import Candidate, Decision
from .verify import check

# (variant) -> (response text, reasoning text): the same prompt, sampled again.
Sample = Callable[[int], Awaitable[tuple[str, str]]]
# (extra user text, variant) -> (response, reasoning): the same prompt plus a note.
Ask = Callable[[str, int], Awaitable[tuple[str, str]]]
# () -> (response, reasoning): the same prompt with the model's reasoning switched on.
Think = Callable[[], Awaitable[tuple[str, str]]]


@dataclass
class StepContext:
    cfg: dict[str, Any]
    state: TurnState
    sample: Sample
    ask: Ask
    tool_names: Iterable[str] | None = None
    last_response: str | None = None
    parser: Callable[[str], Any] | None = None
    final_tools: tuple[str, ...] = FINAL_TOOLS
    # None when the host cannot switch reasoning on for a single call.
    think: Think | None = None
    # A second sample the host started alongside the first call, if any.
    early_second: "asyncio.Future[tuple[str, str]] | None" = None

    def candidate(self, raw: str, reasoning: str, label: str) -> Candidate:
        built = build_candidate(raw, reasoning, label=label, parser=self.parser,
                                final_tools=self.final_tools)
        return check(built, tool_names=self.tool_names,
                     last_response=self.last_response)

    async def _extra(self, call: Awaitable[tuple[str, str]], label: str,
                     decision: Decision) -> Candidate | None:
        decision.extra_calls += 1
        try:
            raw, reasoning = await call
        except asyncio.CancelledError:
            raise
        except Exception:
            return None
        built = self.candidate(raw, reasoning, label)
        decision.candidates.append(built)
        return built

    async def extra_sample(self, variant: int, label: str,
                           decision: Decision) -> Candidate | None:
        if variant == 1 and self.early_second is not None:
            call, self.early_second = self.early_second, None
            return await self._extra(call, label, decision)
        return await self._extra(self.sample(variant), label, decision)

    async def extra_ask(self, text: str, label: str,
                        decision: Decision) -> Candidate | None:
        return await self._extra(self.ask(text, 0), label, decision)

    async def extra_think(self, label: str, decision: Decision) -> Candidate | None:
        if self.think is None:
            return None
        return await self._extra(self.think(), label, decision)

    def drop_early(self) -> None:
        if self.early_second is not None:
            self.early_second.cancel()
            self.early_second = None


async def resolve_step(
    raw: str,
    reasoning: str,
    iteration: int,
    ctx: StepContext,
    chat_mode: str | None = None,
) -> Decision:
    """Classify the host's own candidate and, at a checkpoint, look twice."""
    started = time.monotonic()
    first = ctx.candidate(raw, reasoning, "A")
    reason = checkpoint(ctx.cfg, ctx.state, first, iteration, chat_mode)
    strategies = ctx.cfg["strategies"]
    if reason is None or not (strategies["deepen"]["enabled"] or strategies["agree"]["enabled"]
                              or strategies["escalate"]["enabled"]):
        ctx.drop_early()
        return Decision(winner=first, candidates=[first])

    if strategies["deepen"]["enabled"]:
        ctx.drop_early()
        decision = await deepen.resolve(first, ctx, reason)
    elif strategies["escalate"]["enabled"]:
        decision = await escalate.resolve(first, ctx, reason)
    else:
        decision = await agree.resolve(first, ctx, reason)
    ctx.drop_early()

    ctx.state.extra_calls += decision.extra_calls
    if ctx.state.retry_armed:
        ctx.state.retry_armed = False
        ctx.state.retries_used += 1
    decision.elapsed = time.monotonic() - started
    return decision
