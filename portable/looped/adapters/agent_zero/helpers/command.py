"""Parse and apply the ``/looped`` command. No host imports: testable alone."""

from __future__ import annotations

import re
from typing import Any

MODE_KEY = "looped_mode"      # per-chat mode, saved with the chat
ARM_KEY = "_looped_once"      # one-shot arm for the next turn, never saved

_MODE_WORDS = {"on": "always", "always": "always", "auto": "auto",
               "manual": "manual", "off": "off"}
_PREFIX = re.compile(r"^\s*/looped(?=\s|$)", re.IGNORECASE)
_POSTFIX = re.compile(r"(?<=\s)/looped\s*$", re.IGNORECASE)


def parse(text: Any) -> tuple[str, str | None, str] | None:
    """Return ``(action, value, remaining message)`` or ``None`` if no command.

    ``/looped`` alone or followed by a message arms the next turn; a mode word
    (``on``, ``off``, ``auto``, ``always``, ``manual``) sets the chat's mode;
    ``status`` reports it. ``message /looped`` also arms.
    """
    if not isinstance(text, str):
        return None
    match = _PREFIX.match(text)
    if not match:
        postfix = _POSTFIX.search(text)
        if not postfix:
            return None
        return "arm", None, text[:postfix.start()].strip()
    rest = text[match.end():].strip()
    word, _, tail = rest.partition(" ")
    lowered = word.lower()
    if lowered in _MODE_WORDS:
        return "mode", _MODE_WORDS[lowered], tail.strip()
    if lowered == "status":
        return "status", None, tail.strip()
    if lowered == "once":
        return "arm", None, tail.strip()
    return "arm", None, rest


def describe(data: dict[str, Any], default_mode: str) -> str:
    mode = data.get(MODE_KEY)
    shown = f"{mode} (this chat)" if mode else f"{default_mode} (default)"
    armed = ", armed for the next message" if data.get(ARM_KEY) else ""
    return f"Looped mode: {shown}{armed}."


def apply(data: dict[str, Any], parsed: tuple[str, str | None, str],
          default_mode: str = "manual") -> tuple[str, str]:
    """Apply a parsed command to the chat's data. Returns ``(rest, note)``."""
    action, value, rest = parsed
    if action == "mode":
        data[MODE_KEY] = value
        if value == "off":
            data.pop(ARM_KEY, None)
        note = f"Looped mode set to {value} for this chat."
    elif action == "status":
        note = describe(data, default_mode)
    else:
        data[ARM_KEY] = True
        note = ("Looped mode is on for this message." if rest
                else "Looped mode armed for your next message.")
    return rest, note


def handle(data: dict[str, Any], text: Any,
           default_mode: str = "manual") -> tuple[str, str] | None:
    parsed = parse(text)
    return apply(data, parsed, default_mode) if parsed else None
