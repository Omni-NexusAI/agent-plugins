"""Prompt repetition: show the current task a second time.

A model reads left to right, so on the second copy every token can attend to
the whole first copy. Measured gains are for models answering without a
thinking phase; with thinking on it does nothing, so the default skips it.
"""

from __future__ import annotations

from typing import Any

from ..prompts import REREAD


def build(task: str, cfg: dict[str, Any], thinking: bool = False) -> str | None:
    settings = cfg["strategies"]["reread"]
    if not settings["enabled"] or settings["when"] == "never":
        return None
    if settings["when"] == "non_thinking" and thinking:
        return None
    text = task.strip() if isinstance(task, str) else ""
    # Repeating half a task would change its meaning, so an oversized task is
    # skipped instead of truncated.
    if not text or len(text) > settings["max_chars"]:
        return None
    return REREAD.format(task=text)
