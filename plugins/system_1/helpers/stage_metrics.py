"""Privacy-safe timing aggregates at verified Agent Zero hook boundaries."""

from __future__ import annotations

import time


_ATTRIBUTE = "_system_1_stage_metrics"
_STAGES = ("prompt_preparation", "main_foreground", "main_background",
           "tool_execution", "memory_recall")
_MAX_SPANS = 256


def _record(agent) -> dict:
    record = getattr(agent, _ATTRIBUTE, None)
    if not isinstance(record, dict):
        record = {"active": {}, "totals": {}, "origin": time.monotonic(),
                  "spans": [], "dropped_spans": 0}
        setattr(agent, _ATTRIBUTE, record)
    else:
        # Existing chats can survive a plugin hot reload with the prior
        # aggregate-only record. Add span state without discarding totals.
        record.setdefault("active", {})
        record.setdefault("totals", {})
        if "origin" not in record:
            record["origin"] = time.monotonic()
        record.setdefault("spans", [])
        record.setdefault("dropped_spans", 0)
    return record


def begin(agent, stage: str, token=None) -> None:
    if stage not in _STAGES:
        return
    active = _record(agent)["active"]
    if len(active) >= 32:
        active.clear()  # A failed host call must not retain unbounded markers.
    active[(stage, id(token) if token is not None else None)] = time.monotonic()


def finish(agent, stage: str, token=None) -> None:
    if stage not in _STAGES:
        return
    record = _record(agent)
    started = record["active"].pop(
        (stage, id(token) if token is not None else None), None)
    if started is None:
        return
    total = record["totals"].setdefault(stage, {"calls": 0, "seconds": 0.0})
    total["calls"] += 1
    ended = time.monotonic()
    total["seconds"] += max(0.0, ended - started)
    spans = record["spans"]
    if len(spans) >= _MAX_SPANS:
        spans.pop(0)
        record["dropped_spans"] += 1
    spans.append({"stage": stage,
                  "start": max(0.0, started - record["origin"]),
                  "end": max(0.0, ended - record["origin"])})


def snapshot(agent) -> dict:
    totals = _record(agent)["totals"]
    return {stage: {"calls": int(totals.get(stage, {}).get("calls", 0)),
                    "seconds": float(totals.get(stage, {}).get("seconds", 0.0))}
            for stage in _STAGES}


def spans_snapshot(agent) -> dict:
    """Bounded relative timings for overlap analysis; no request or tool data."""
    record = _record(agent)
    return {"spans": [dict(span) for span in record["spans"]],
            "dropped": int(record["dropped_spans"])}
