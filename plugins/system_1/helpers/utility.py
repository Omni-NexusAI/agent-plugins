"""Opt-in finite Utility responses with the host Utility model as fallback."""

from __future__ import annotations

from copy import deepcopy
import math
import time

from usr.plugins.system_1.helpers.runtime import client_for, config_for


_METRICS = "_system_1_utility_metrics"
_MAX_RESPONSE_CHARS = 4000


class UtilityRouteResult:
    """Whether an exact route was tried and whether it bypassed Utility."""

    __slots__ = ("attempted", "bypassed")

    def __init__(self, attempted: bool, bypassed: bool):
        self.attempted = attempted
        self.bypassed = bypassed

    def __bool__(self) -> bool:
        return self.bypassed


INELIGIBLE = UtilityRouteResult(False, False)
FALLBACK = UtilityRouteResult(True, False)
BYPASS = UtilityRouteResult(True, True)


def metrics(agent) -> dict:
    """Per-agent counters; no prompt, response, or credential is retained."""
    current = getattr(agent, _METRICS, None)
    if not isinstance(current, dict):
        current = {"calls": 0, "decisions": 0, "bypassed": 0, "fallbacks": 0,
                   "decision_seconds": 0.0, "fallback_model_seconds": 0.0}
        setattr(agent, _METRICS, current)
    else:
        current.setdefault("calls", 0)  # Hot-loaded instances may have older counters.
    return current


def _threshold(policy: dict) -> float:
    value = float(policy.get("min_choice_probability", 0.85))
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Invalid Utility decision threshold")
    return value


def _match_route(section: dict, call_data: dict) -> dict | None:
    routes = section.get("fixed_routes", [])
    if not isinstance(routes, list) or len(routes) > 32:
        return None
    system, message = call_data.get("system"), call_data.get("message")
    if not isinstance(system, str) or not isinstance(message, str):
        return None
    matches = [route for route in routes if isinstance(route, dict)
               and route.get("system") == system and route.get("message") == message]
    if len(matches) != 1:
        return None
    route = matches[0]
    responses = route.get("responses")
    if (not isinstance(responses, dict) or not 1 <= len(responses) <= 254
            or any(not isinstance(key, str) or not key or key == "ordinary"
                   or not isinstance(value, str) or not value
                   or len(value) > _MAX_RESPONSE_CHARS
                   for key, value in responses.items())):
        return None
    return route


class FixedUtilityModel:
    """Use the fixed result only if the host still sends the matched request."""

    def __init__(self, original, system: str, message: str, response: str,
                 section: dict, confidence: float, agent):
        self.original = original
        self.system = system
        self.message = message
        self.response = response
        self.section = section
        self.confidence = confidence
        self.agent = agent

    async def unified_call(self, *, system_message: str, user_message: str,
                           response_callback=None, **kwargs):
        try:
            current = config_for(self.agent, "utility")
        except Exception:
            current = None
        if (system_message != self.system or user_message != self.message
                or not current or current[0] != self.section
                or not self._confidence_still_qualifies(current[1])):
            start = time.monotonic()
            try:
                return await self.original.unified_call(
                    system_message=system_message, user_message=user_message,
                    response_callback=response_callback, **kwargs)
            finally:
                result = metrics(self.agent)
                result["fallbacks"] += 1
                result["fallback_model_seconds"] += max(0.0, time.monotonic() - start)
        metrics(self.agent)["bypassed"] += 1
        if response_callback:
            await response_callback(self.response, self.response)
        return self.response, ""

    def _confidence_still_qualifies(self, policy: dict) -> bool:
        try:
            return self.confidence >= _threshold(policy)
        except (TypeError, ValueError, OverflowError):
            return False


async def install_fixed_utility_response(agent, call_data: dict) -> UtilityRouteResult:
    """Install a guarded fixed response for an exact, explicitly configured call."""
    try:
        settings = config_for(agent, "utility")
    except Exception:
        return INELIGIBLE
    if not settings or not isinstance(call_data, dict) or "model" not in call_data:
        return INELIGIBLE
    section, policy = settings
    # Chat confidence is self-reported and cannot authorize a direct response.
    if section.get("backend") not in {"jev", "openrouter", "llama_decision"}:
        return INELIGIBLE
    route = _match_route(section, call_data)
    if route is None:
        return INELIGIBLE
    try:
        route = deepcopy(route)
        section_snapshot = deepcopy(section)
        message = call_data["message"]
        system = call_data["system"]
        limit = min(16000, max(1, int(policy.get("max_state_chars", 4000))))
        if not message:
            return INELIGIBLE
        threshold = _threshold(policy)
        choices = {"ordinary": "Use the original Utility model."}
        choices.update({key: f"Return this exact configured response: {value}"
                        for key, value in route["responses"].items()})
        decision_state = f"System instruction: {system}\nUser message: {message}"
        if len(decision_state) + sum(len(value) for value in choices.values()) > limit:
            return INELIGIBLE
        record = metrics(agent)
        record["decisions"] += 1
        start = time.monotonic()
        try:
            decision = await client_for(section, policy).choose(decision_state, choices)
        finally:
            record["decision_seconds"] += max(0.0, time.monotonic() - start)
        # Recheck mutable configuration and request after the remote decision.
        current = config_for(agent, "utility")
        if (not current or current[0] != section_snapshot
                or _match_route(current[0], call_data) != route
                or call_data["system"] != system or call_data["message"] != message
                or decision.choice not in route["responses"]
                or not isinstance(decision.confidence, (int, float))
                or not math.isfinite(decision.confidence)
                or not 0 <= decision.confidence <= 1
                or decision.confidence < _threshold(current[1])):
            record["fallbacks"] += 1
            return FALLBACK
        call_data["model"] = FixedUtilityModel(
            call_data["model"], system, message,
            route["responses"][decision.choice], section_snapshot,
            decision.confidence, agent)
        return BYPASS
    except Exception:
        metrics(agent)["fallbacks"] += 1
        return FALLBACK
