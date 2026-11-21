"""`/looped` for hosts with the built-in slash-command catalog."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from usr.plugins.looped.helpers import command, runtime
    except ImportError:
        from plugins.looped.helpers import command, runtime
    from agent import AgentContext

    invocation = payload.get("invocation") or {}
    context_id = str((payload.get("context") or {}).get("context_id") or "")
    context = AgentContext.get(context_id) if context_id else None
    if not context:
        return {"text": "", "effects": [
            {"type": "toast", "message": "Open a chat before using /looped."}]}

    raw = str(invocation.get("raw_arguments") or "").strip()
    default_mode = runtime.config(context.agent0)["mode"]
    rest, note = command.handle(context.data, f"/looped {raw}".strip(), default_mode)
    return {"text": rest, "effects": [{"type": "toast", "message": note}]}
