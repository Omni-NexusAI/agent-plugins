"""Warn-and-confirm gate for anything that sends requests to a real model.

A local router that keeps one model loaded will unload it when asked for a
different one, and a single-slot server queues benchmark requests with the
user's own sessions and overwrites their prompt cache. So before the first
live request this prints exactly what will be touched and requires the model
name to be typed back. It refuses outright when the request would make the
server swap models, unless that is explicitly allowed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


def model_state(endpoint: str, model: str, api_key: str = "", timeout: float = 8.0) -> dict[str, Any]:
    """Read-only look at ``/models``. Never loads anything."""
    request = urllib.request.Request(endpoint.rstrip("/") + "/models")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return {"reachable": True, "listed": None, "loaded": None, "note": f"HTTP {error.code}"}
    except Exception as error:
        return {"reachable": False, "listed": None, "loaded": None, "note": str(error)}
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return {"reachable": True, "listed": None, "loaded": None, "note": "unexpected reply"}
    loaded_ids, sleeping_ids, listed = [], [], False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        value = status.get("value") if isinstance(status, dict) else status
        if entry.get("id") == model:
            listed = True
        if value == "loaded":
            loaded_ids.append(entry.get("id"))
        elif value == "sleeping":       # router keeps the model's process, weights dropped when idle
            sleeping_ids.append(entry.get("id"))
    statuses_known = any(isinstance(entry, dict) and "status" in entry for entry in entries)
    busy = False
    if not statuses_known:
        # Routers whose model list carries no state may report it at <origin>/status.
        origin = endpoint.rstrip("/")
        origin = origin[:-3] if origin.endswith("/v1") else origin
        request = urllib.request.Request(origin + "/status")
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                parsed = from_status(json.loads(response.read().decode("utf-8")))
        except Exception:
            parsed = None
        if parsed is not None:
            loaded_ids, busy = parsed
            statuses_known = True
    loaded = (model in loaded_ids) if statuses_known else None
    return {"reachable": True, "listed": listed, "loaded": loaded,
            "loaded_models": loaded_ids, "sleeping_models": sleeping_ids,
            "asleep": model in sleeping_ids, "busy": busy, "note": ""}


def from_status(data: Any) -> tuple[list[str], bool] | None:
    """Read a router ``/status`` reply: (loaded model ids, working right now).

    Understands ``{"state", "model", "active", "queued", "models": [{"id",
    "loaded"}]}``. Returns None when the reply has no usable model state.
    """
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return None
    entries = [entry for entry in data["models"] if isinstance(entry, dict) and "loaded" in entry]
    if not entries:
        return None
    loaded = [str(entry.get("id")) for entry in entries if entry.get("loaded") is True]
    current = data.get("model")
    if isinstance(current, str) and current and data.get("state") not in (None, "unloaded") \
            and current not in loaded:
        loaded.append(current)          # loading or loaded, but not yet flagged in the list
    busy = bool(data.get("active")) or bool(data.get("queued"))
    return loaded, busy


def confirm_live(endpoint: str, model: str, requests: int, concurrency: int, *,
                 api_key: str = "", allow_model_swap: bool = False,
                 allow_unknown_state: bool = False, assume_yes: bool = False,
                 ask: Callable[[str], str] = input,
                 say: Callable[[str], None] = print,
                 probe: Callable[..., dict[str, Any]] = model_state) -> bool:
    """Return True only when it is safe and confirmed to send live requests."""
    state = probe(endpoint, model, api_key)
    say("")
    say("LIVE MODEL RUN - this will send requests to a real model server.")
    say(f"  endpoint:     {endpoint}")
    say(f"  model:        {model}")
    say(f"  requests:     about {requests}, {concurrency} at a time")
    if not state["reachable"]:
        say(f"  server:       not reachable ({state['note']})")
        say("Refusing: the server could not be reached.")
        return False
    held = [str(item) for item in (state.get("loaded_models") or []) + (state.get("sleeping_models") or [])
            if item != model]
    if state["loaded"] is True:
        say("  model state:  already loaded (no model swap)")
    elif state["loaded"] is False and state.get("asleep") and not held:
        say("  model state:  asleep (idle). The first request wakes it and reloads it into GPU")
        say("                memory, which can take a minute. No other model is loaded or asleep,")
        say("                so nothing is displaced.")
    elif state["loaded"] is False and not held:
        say("  model state:  not loaded, and no other model is loaded or asleep, so nothing is")
        say("                displaced. The first request loads it into GPU memory, which can")
        say("                take a minute.")
    elif state["loaded"] is False:
        others = ", ".join(held) or "none"
        say(f"  model state:  NOT loaded. Currently loaded or asleep: {others}")
        say("  A request would make the server load this model and may unload the one in use.")
        if not allow_model_swap:
            say("Refusing: pass --allow-model-swap to permit loading a different model.")
            return False
    else:
        say(f"  model state:  unknown ({state['note'] or 'server does not report it'})")
        if not allow_unknown_state:
            say("Refusing: cannot tell whether this would swap models. "
                "Pass --allow-unknown-state if you know it will not.")
            return False
    if state.get("busy"):
        say("  in use now:   the server is working on, or has queued, someone else's request.")
        say("                Benchmark requests will wait behind it and slow it down.")
    say("  effect on running sessions: requests share the server's slots, so they queue")
    say("  with anything else using this model, and a single-slot server's prompt cache")
    say("  is overwritten (the other session re-reads its whole prompt on its next turn).")
    say("  GPU: the model's normal inference load for the duration of the run.")
    if assume_yes:
        say("Confirmed by --yes.")
        return True
    typed = ask(f"Type the model name ({model}) to start, anything else to cancel: ")
    if typed.strip() != model:
        say("Cancelled. Nothing was sent.")
        return False
    return True
