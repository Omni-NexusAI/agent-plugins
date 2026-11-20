"""Shared test helpers: import path and a scripted fake model."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import StepContext, TurnState, merge_config  # noqa: E402


def step(tool: str, **args) -> str:
    return json.dumps({"thoughts": ["t"], "headline": "h", "tool_name": tool,
                       "tool_args": args})


def final(text: str) -> str:
    return step("response", text=text)


class FakeModel:
    """Replays scripted responses and records how it was called."""

    def __init__(self, samples=(), asks=()):
        self.samples = list(samples)
        self.asks = list(asks)
        self.sample_calls: list[int] = []
        self.ask_calls: list[str] = []

    async def sample(self, variant: int):
        self.sample_calls.append(variant)
        item = self.samples.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, ""

    async def ask(self, text: str, variant: int):
        self.ask_calls.append(text)
        item = self.asks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, ""

    @property
    def calls(self) -> int:
        return len(self.sample_calls) + len(self.ask_calls)


def context(model: FakeModel, settings=None, state=None, **kwargs) -> StepContext:
    return StepContext(cfg=merge_config(settings), state=state or TurnState(),
                       sample=model.sample, ask=model.ask, **kwargs)


def run(coro):
    return asyncio.run(coro)
