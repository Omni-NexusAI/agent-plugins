"""Decide when looped mode acts: mode, checkpoints and budget."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from .config import MODES
from .types import Candidate


@dataclass
class TurnState:
    """Per-turn state. A host resets it when a new user turn starts."""

    armed: bool = False           # manual mode: the user armed this turn
    extra_calls: int = 0
    retry_armed: bool = False     # a tool just failed; look twice at the next step
    retries_used: int = 0
    plan_done: bool = False

    def remaining(self, cfg: dict[str, Any]) -> int:
        return max(0, int(cfg["budget"]["max_extra_calls_per_turn"]) - self.extra_calls)


def effective_mode(cfg: dict[str, Any], chat_mode: str | None = None) -> str:
    """A per-chat mode, when set, overrides the saved default."""
    return chat_mode if chat_mode in MODES else cfg["mode"]


def is_active(cfg: dict[str, Any], state: TurnState, chat_mode: str | None = None) -> bool:
    mode = effective_mode(cfg, chat_mode)
    if mode == "off":
        return False
    if mode == "manual":
        return state.armed
    return True


def is_risky(tool_name: str, patterns: list[str]) -> bool:
    name = tool_name.strip().lower()
    base = name.split(":")[0]
    return any(fnmatchcase(name, pattern.lower()) or fnmatchcase(base, pattern.lower())
               for pattern in patterns)


def checkpoint(
    cfg: dict[str, Any],
    state: TurnState,
    candidate: Candidate,
    iteration: int,
    chat_mode: str | None = None,
) -> str | None:
    """Return why this step deserves a second look, or ``None`` to pass through."""
    if not is_active(cfg, state, chat_mode):
        return None
    if state.remaining(cfg) <= 0 or cfg["budget"]["max_extra_calls_per_step"] <= 0:
        return None
    if state.armed:
        return "armed"
    if effective_mode(cfg, chat_mode) == "always":
        return "always"
    enabled = cfg["auto"]["checkpoints"]
    if "invalid_step" in enabled and not candidate.valid:
        return "invalid_step"
    if "after_error" in enabled and state.retry_armed:
        return "after_error"
    if "final_response" in enabled and candidate.kind == "final":
        return "final_response"
    if "risky_tool" in enabled and candidate.kind == "action" \
            and is_risky(candidate.tool_name, cfg["auto"]["risky_tools"]):
        return "risky_tool"
    if "first_step" in enabled and iteration <= 0:
        return "first_step"
    return None
