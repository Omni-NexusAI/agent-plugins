"""Validate Agent Zero's native parallel-tool result before sharing child evidence."""

from __future__ import annotations

import json
import re


_STATES = {"pending", "running", "success", "error", "cancelled", "timeout"}
_STATUSES = {"started", "success", "partial", "error", "cancelled", "running", "waiting"}
_JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


def parse_parallel_jobs(masked_json: str, batch: list[dict],
                        job_ids: list[str] | None = None) -> list[dict] | None:
    """Return ordered, validated job snapshots or ``None`` on any mismatch.

    The caller must mask the complete host result before passing it here. A
    started job is not an observation of its eventual tool result; callers
    must await it and validate the collected snapshot separately.
    """
    if (not isinstance(masked_json, str) or len(masked_json) > 2_000_000 or
            not isinstance(batch, list) or not 1 <= len(batch) <= 8 or
            (job_ids is not None and
             (not isinstance(job_ids, list) or len(job_ids) != len(batch) or
              len(set(job_ids)) != len(job_ids) or
              any(not isinstance(value, str) or not _JOB_ID.fullmatch(value)
                  for value in job_ids)))):
        return None
    try:
        payload = json.loads(masked_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("status") not in _STATUSES:
        return None
    jobs = payload.get("jobs")
    # A later await can collect unrelated Main-owned jobs from several native
    # batches. Keep each submitted System 1 batch at eight, but allow a larger
    # bounded await payload and select only the tracked IDs below.
    max_jobs = 64 if job_ids is not None else 8
    if (not isinstance(jobs, list) or not 1 <= len(jobs) <= max_jobs or
            (job_ids is None and len(jobs) != len(batch))):
        return None
    # A start or synchronous wait returns the whole batch in submission order.
    # A later native await may return any subset in any order. Match those jobs
    # by their recorded IDs, never by position or by tool name alone.
    expected_by_id = ({job_id: (index, batch[index])
                       for index, job_id in enumerate(job_ids)}
                      if job_ids is not None else None)
    parsed = []
    seen_ids = set()
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            return None
        job_id = job.get("job_id")
        if (not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id) or
                job_id in seen_ids):
            return None
        seen_ids.add(job_id)
        if expected_by_id is not None and job_id not in expected_by_id:
            # Main can await its own native jobs together with our jobs. Only
            # tracked children may become System 1 observations.
            continue
        batch_index, expected = (expected_by_id[job_id]
                                 if expected_by_id is not None
                                 else (index, batch[index]))
        if not isinstance(expected, dict):
            return None
        tool_name = job.get("tool_name")
        state = job.get("state")
        if tool_name != expected.get("tool_name") or state not in _STATES:
            return None
        result = job.get("result")
        error = job.get("error")
        if ((result is not None and not isinstance(result, str)) or
                (error is not None and not isinstance(error, str)) or
                (state == "success" and payload["status"] != "started" and
                 not isinstance(result, str))):
            return None
        parsed.append({"job_id": job_id, "batch_index": batch_index,
                       "tool_name": tool_name, "state": state,
                       "result": result or "", "error": error or ""})
    return parsed
