"""Counters only. No prompt text, arguments or credentials are retained."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .types import Decision


class Metrics:
    def __init__(self) -> None:
        self.steps = 0
        self.checked = 0
        self.extra_calls = 0
        self.changed = 0
        self.elapsed = 0.0
        self.outcomes: Counter[str] = Counter()
        self.reasons: Counter[str] = Counter()

    def record(self, decision: Decision) -> None:
        self.steps += 1
        if decision.strategy == "none":
            return
        self.checked += 1
        self.extra_calls += decision.extra_calls
        self.elapsed += decision.elapsed
        self.outcomes[decision.outcome] += 1
        self.reasons[decision.reason] += 1
        if decision.changed:
            self.changed += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "checked": self.checked,
            "extra_calls": self.extra_calls,
            "changed": self.changed,
            "elapsed_ms": int(self.elapsed * 1000),
            "calls_per_step": round(1 + self.extra_calls / self.steps, 3) if self.steps else 1.0,
            "outcomes": dict(self.outcomes),
            "reasons": dict(self.reasons),
        }
