from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

try:
    from usr.plugins.agent_harness.helpers.models import CheckpointRecord
except ImportError:
    CheckpointRecord = None


LOGGER = logging.getLogger(__name__)

# Outbound-only Telegram notification path for Daniel. Does not read, write, or mutate
# Agent Zero API-key/secret config files.
TELEGRAM_BOT_TOKEN = "8627717200:AAGV7XtqFxAY3cEjJipj6fK9_HVPQ5fRhlc"
TELEGRAM_CHAT_ID = 6174226840
TELEGRAM_SEND_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# Per-process dedupe to prevent repeated guardrail-loop spam for the same pending checkpoint.
_NOTIFIED_CHECKPOINT_IDS: set[str] = set()


def _truncate(value: Any, limit: int = 900) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _message_for_checkpoint(checkpoint: CheckpointRecord, *, source: str) -> str:
    reason = _truncate(checkpoint.reason, 900)
    proposed = _truncate(checkpoint.proposed_action, 900)
    risk = _truncate(checkpoint.risk_level, 80)
    tool_name = _truncate(checkpoint.tool_name, 120)

    return (
        "⚠️ Agent Harness checkpoint awaiting approval\n\n"
        f"Source: {source}\n"
        f"Risk: {risk}\n"
        f"Tool: {tool_name}\n\n"
        f"Reason:\n{reason}\n\n"
        f"Pending action:\n{proposed}\n\n"
        "Please approve or reject the checkpoint in Agent Zero."
    )


def notify_checkpoint_pending(checkpoint: CheckpointRecord, *, source: str) -> bool:
    """Notify Daniel that a harness checkpoint is pending.

    Returns True when Telegram accepted the request. Failures are logged and
    swallowed so notification problems never break the harness itself.
    """
    if checkpoint.id in _NOTIFIED_CHECKPOINT_IDS:
        return False

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": _message_for_checkpoint(checkpoint, source=source),
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        TELEGRAM_SEND_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body)
        if parsed.get("ok") is True:
            _NOTIFIED_CHECKPOINT_IDS.add(checkpoint.id)
            return True
        LOGGER.warning("Telegram checkpoint notification rejected: %s", body)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        LOGGER.warning("Telegram checkpoint notification failed: %s", exc)
    return False
