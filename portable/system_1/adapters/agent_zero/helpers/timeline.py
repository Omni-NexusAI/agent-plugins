"""Small, non-authoritative chat timeline records for Main System 1 decisions."""

from __future__ import annotations

import time
import uuid

from helpers import plugins


KEY = "system_1_main_timeline"


def _temporary(agent):
    loop_data = getattr(agent, "loop_data", None)
    params = getattr(loop_data, "params_temporary", None)
    return params if isinstance(params, dict) else None


def start_main_step(agent) -> None:
    """Create a native process step before each eligible System 1 decision."""
    try:
        params = _temporary(agent)
        if params is None or KEY in params:
            return
        from usr.plugins.system_1.helpers.runtime import should_decide

        if not should_decide(agent):
            return
        config = plugins.get_plugin_config("system_1", agent)
        main = config.get("main", {}) if isinstance(config, dict) else {}
        if not isinstance(main, dict) or not main.get("enabled"):
            return
        message = getattr(agent, "last_user_message", None)
        if not message or not message.output_text().strip():
            return
        backend = str(main.get("backend", "unconfigured"))[:40]
        item = agent.context.log.log(
            type="info", heading="System 1 · Main: deciding",
            id=f"system1-main-{uuid.uuid4().hex}",
            kvps={"Backend": backend, "Route": "Deciding"},
        )
        params[KEY] = {"item": item, "started": time.monotonic(), "backend": backend}
    except Exception:
        # Observability must never prevent the host's normal model call.
        return


def finish_main_step(agent, route: str, *, confidence: float | None = None,
                     detail: str = "", action_name: str = "") -> None:
    """Finalize the same record without storing prompts, arguments, or secrets."""
    try:
        params = _temporary(agent)
        record = params.get(KEY) if params else None
        if not record or record.get("finished"):
            return
        record["finished"] = True
        elapsed = max(0, time.monotonic() - record["started"])
        kvps = {"Backend": record["backend"], "Route": route,
                "Elapsed": f"{elapsed:.2f} s"}
        if confidence is not None:
            kvps["Confidence"] = f"{confidence:.1%}"
        if action_name:
            kvps["Action"] = str(action_name)[:120]
        if detail:
            kvps["Outcome"] = detail
        record["item"].update(heading=f"System 1 · Main: {route.lower()}", kvps=kvps)
    except Exception:
        return


def record_main_observation(agent, tool_name: str) -> None:
    """Show that a submitted action produced a host-recorded result.

    Keep the result in native Tool history; this Info step contains no result
    text, arguments, or request content.
    """
    try:
        if not isinstance(tool_name, str) or not tool_name:
            return
        agent.context.log.log(
            type="info", heading="System 1 · Main: observed tool result",
            id=f"system1-main-{uuid.uuid4().hex}",
            kvps={"Route": "Observed tool result", "Action": tool_name[:120],
                  "Outcome": "Available for the next decision"},
        )
    except Exception:
        # Logging cannot change whether the host's tool result is accepted.
        return
