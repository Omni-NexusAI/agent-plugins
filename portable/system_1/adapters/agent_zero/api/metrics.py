"""Read-only, per-chat System 1 counters for practical Utility comparisons."""

from agent import AgentContext
from helpers.api import ApiHandler, Request, Response
from usr.plugins.system_1.helpers.stage_metrics import snapshot as stage_snapshot


_COUNT_KEYS = ("calls", "decisions", "bypassed", "fallbacks",
               "ordinary_generations", "fallback_model_calls")
_TIME_KEYS = ("decision_seconds", "bypass_seconds",
              "fallback_model_seconds", "ordinary_model_seconds")


class Metrics(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        context_id = input.get("context")
        if not isinstance(context_id, str) or not context_id:
            return Response(status=400, response="A chat context is required")
        context = AgentContext.get(context_id)
        if context is None or context.agent0 is None:
            return Response(status=404, response="Chat context not found")
        raw = getattr(context.agent0, "_system_1_utility_metrics", None)
        raw = raw if isinstance(raw, dict) else {}
        counts = {key: max(0, int(raw.get(key, 0))) for key in _COUNT_KEYS}
        seconds = {key: max(0.0, float(raw.get(key, 0.0))) for key in _TIME_KEYS}
        return {"ok": True, "utility": {**counts, **seconds},
                "stages": stage_snapshot(context.agent0)}
