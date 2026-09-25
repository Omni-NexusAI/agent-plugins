"""Privacy-safe timing aggregates at verified Agent Zero hook boundaries."""

from __future__ import annotations

import time


_ATTRIBUTE = "_system_1_stage_metrics"
_STAGES = ("prompt_preparation", "main_foreground", "main_background",
           "tool_execution", "memory_recall")


def _record(agent) -> dict:
    record = getattr(agent, _ATTRIBUTE, None)
    if not isinstance(record, dict):
        record = {"active": {}, "totals": {}}
        setattr(agent, _ATTRIBUTE, record)
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
    total["seconds"] += max(0.0, time.monotonic() - started)


def snapshot(agent) -> dict:
    totals = _record(agent)["totals"]
    return {stage: {"calls": int(totals.get(stage, {}).get("calls", 0)),
                    "seconds": float(totals.get(stage, {}).get("seconds", 0.0))}
            for stage in _STAGES}
