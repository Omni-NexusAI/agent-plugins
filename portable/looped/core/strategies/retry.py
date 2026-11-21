"""Second look driven by a real failure signal (a tool error), not self-critique."""

from __future__ import annotations

import re
from typing import Any

from ..controller import TurnState

_ERROR = re.compile(
    r"Traceback \(most recent call last\)"
    r"|^\s*\w+(Error|Exception)\b"
    r"|^\s*error[:\s]"
    r"|command not found"
    r"|No such file or directory"
    r"|exit(ed with)? code:? [1-9]"
    r"|tool .{0,80}not found",
    re.IGNORECASE | re.MULTILINE,
)


def looks_like_error(text: Any) -> bool:
    return isinstance(text, str) and bool(_ERROR.search(text[:20_000]))


def note_tool_result(text: Any, cfg: dict[str, Any], state: TurnState,
                     failed: bool | None = None) -> bool:
    """Arm a second look at the next step when a tool failed. Returns armed."""
    settings = cfg["strategies"]["retry"]
    if not settings["enabled"] or state.retries_used >= settings["max_per_turn"]:
        return False
    is_error = looks_like_error(text) if failed is None else bool(failed)
    if is_error:
        state.retry_armed = True
    return is_error
