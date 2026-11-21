"""Programmatic checks on a candidate. These run before any model-based choice."""

from __future__ import annotations

from typing import Iterable

from .types import Candidate


def check(
    candidate: Candidate,
    *,
    tool_names: Iterable[str] | None = None,
    last_response: str | None = None,
) -> Candidate:
    """Mark ``candidate`` invalid when a check fails. Returns the candidate.

    ``tool_names`` is the host's list of callable tools; pass ``None`` when the
    host cannot enumerate them (for example remote tools resolved at call time),
    which skips the existence check instead of guessing.
    """
    if not candidate.valid:
        return candidate
    if tool_names is not None:
        known = {str(name).strip().lower() for name in tool_names}
        name = candidate.tool_name.strip().lower()
        if name not in known and name.split(":")[0] not in known:
            candidate.problems.append("unknown_tool")
    if last_response is not None and candidate.raw.strip() \
            and candidate.raw.strip() == last_response.strip():
        candidate.problems.append("repeat")
    if candidate.problems:
        candidate.kind = "invalid"
    return candidate
