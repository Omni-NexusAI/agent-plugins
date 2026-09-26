"""Read-only, per-chat System 1 counters for practical Utility comparisons."""

from agent import AgentContext
from helpers.api import ApiHandler, Request, Response
from usr.plugins.system_1.helpers.stage_metrics import (
    snapshot as stage_snapshot, spans_snapshot)


_COUNT_KEYS = ("calls", "decisions", "bypassed", "fallbacks",
               "ordinary_generations", "fallback_model_calls")
_TIME_KEYS = ("decision_seconds", "bypass_seconds",
              "fallback_model_seconds", "ordinary_model_seconds")
_MODEL_CATEGORIES = ("memory_query", "memory_filter", "memory_ingestion", "other")
_FILTER_GATE_KEYS = ("seen", "shape_ineligible", "payload_oversize",
                     "decision_attempted", "fallback", "bypass_installed",
                     "reason_template", "reason_message_length",
                     "reason_candidate_format", "reason_candidate_count",
                     "reason_candidate_length", "reason_request_shape",
                     "reason_stale", "reason_choice", "reason_confidence",
                     "reason_error")


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
        raw_categories = raw.get("model_call_categories")
        raw_categories = raw_categories if isinstance(raw_categories, dict) else {}
        categories = {
            name: {"calls": max(0, int(values.get("calls", 0))),
                   "seconds": max(0.0, float(values.get("seconds", 0.0)))}
            for name in _MODEL_CATEGORIES
            if isinstance((values := raw_categories.get(name)), dict)
        }
        raw_gate = raw.get("memory_filter_gate")
        raw_gate = raw_gate if isinstance(raw_gate, dict) else {}
        filter_gate = {name: max(0, int(raw_gate.get(name, 0)))
                       for name in _FILTER_GATE_KEYS}
        return {"ok": True, "utility": {**counts, **seconds,
                                         "model_call_categories": categories,
                                         "memory_filter_gate": filter_gate},
                "stages": stage_snapshot(context.agent0),
                "stage_spans": spans_snapshot(context.agent0)}
