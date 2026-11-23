"""Looped-mode counters for one chat. Counts and timings only."""

from helpers.api import ApiHandler, Request, Response


class Metrics(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        try:
            from usr.plugins.looped.helpers import runtime
        except ImportError:
            from plugins.looped.helpers import runtime
        return {"ok": True,
                "metrics": runtime.metrics_report(str(input.get("context_id") or ""))}
