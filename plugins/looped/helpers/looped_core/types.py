"""Data contracts shared by strategies, adapters and the benchmark."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    """One proposed agent step.

    ``kind`` is ``action`` (a tool call), ``final`` (the answer to the user) or
    ``invalid`` (unparsed or failing a programmatic check).
    """

    raw: str
    reasoning: str = ""
    label: str = "A"
    parsed: dict[str, Any] | None = None
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    kind: str = "invalid"
    key: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.kind != "invalid"


@dataclass
class Decision:
    """Outcome of resolving one step. ``trace`` never contains prompt text."""

    winner: Candidate
    strategy: str = "none"
    outcome: str = "passthrough"
    reason: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    extra_calls: int = 0
    elapsed: float = 0.0

    @property
    def changed(self) -> bool:
        return bool(self.candidates) and self.winner is not self.candidates[0]

    def trace(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "outcome": self.outcome,
            "reason": self.reason,
            "winner": self.winner.label,
            "candidates": [
                {"label": c.label, "kind": c.kind, "tool": c.tool_name,
                 "problems": list(c.problems)}
                for c in self.candidates
            ],
            "extra_calls": self.extra_calls,
            "elapsed_ms": int(self.elapsed * 1000),
        }
