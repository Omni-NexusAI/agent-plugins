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
    loaded_ids, listed = [], False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        value = status.get("value") if isinstance(status, dict) else status
        if entry.get("id") == model:
            listed = True
        if value == "loaded":
            loaded_ids.append(entry.get("id"))
    statuses_known = any(isinstance(entry, dict) and "status" in entry for entry in entries)
    loaded = (model in loaded_ids) if statuses_known else None
    return {"reachable": True, "listed": listed, "loaded": loaded,
            "loaded_models": loaded_ids, "note": ""}


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
    if state["loaded"] is True:
        say("  model state:  already loaded (no model swap)")
    elif state["loaded"] is False:
        others = ", ".join(str(item) for item in state.get("loaded_models") or []) or "none"
        say(f"  model state:  NOT loaded. Currently loaded: {others}")
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
