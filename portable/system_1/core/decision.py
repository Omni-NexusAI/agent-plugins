"""Finite-choice decision clients. No host tools are called from this module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
from typing import Mapping
from urllib.request import Request, urlopen


class DecisionError(RuntimeError):
    """A backend was unavailable or returned a malformed decision."""


@dataclass(frozen=True)
class Choice:
    id: str
    description: str


@dataclass(frozen=True)
class Decision:
    choice: str
    confidence: float
    backend: str


def _post(url: str, payload: dict, token: str, timeout: float) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, json.dumps(payload).encode("utf-8"), headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        data = response.read(1_048_577)
    if len(data) > 1_048_576:
        raise DecisionError("Decision response is too large")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise DecisionError("Decision response must be an object")
    return result


class DecisionClient:
    def __init__(self, *, backend: str, model: str, endpoint: str = "", token: str = "", timeout: float = 2.0):
        if backend not in {"jev", "openrouter", "llama_decision"}:
            raise ValueError("Unsupported decision backend")
        if not model.strip():
            raise ValueError("Decision model is required")
        if not 0.1 <= timeout <= 30:
            raise ValueError("Decision timeout must be between 0.1 and 30 seconds")
        self.backend, self.model, self.token, self.timeout = backend, model.strip(), token, timeout
        defaults = {"jev": "https://api.typesafe.ai/v1/systemone",
                    "openrouter": "https://openrouter.ai/api/alpha/decisions"}
        self.endpoint = endpoint.strip() or defaults.get(backend, "")
        if not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("Decision endpoint must be HTTP(S)")
        if backend in {"jev", "openrouter"} and not self.endpoint.startswith("https://"):
            raise ValueError("Hosted decision services require HTTPS")

    async def choose(self, state: str, choices: Mapping[str, str]) -> Decision:
        if not state or len(state) > 16_000:
            raise ValueError("Decision state must be 1 to 16000 characters")
        if not 2 <= len(choices) <= 255 or any(not key or not isinstance(value, str) for key, value in choices.items()):
            raise ValueError("Decision choices must be 2 to 255 named descriptions")
        ids = list(choices)
        if self.backend in {"jev", "openrouter"}:
            model = self.model
            if self.backend == "openrouter" and model == "typesafe/jev-latest":
                model = "~typesafe/jev-latest"
            payload = {"state": state, "model": model, "questions": {"route": {
                "type": "choice", "instructions": "Select exactly one permitted next step for this agent state.",
                "criteria": dict(choices)}}}
            url = self.endpoint
        else:
            payload = {"model": self.model, "instructions": "Select exactly one permitted next step for this agent state.",
                       "schema": {"route": {"type": "enum", "choices": ids, "description": "Permitted next step"}},
                       "contexts": [state]}
            url = self.endpoint.rstrip("/")
            if not url.endswith("/v1/decision"):
                url += "/v1/decision"
        try:
            result = await asyncio.to_thread(_post, url, payload, self.token, self.timeout)
            if self.backend in {"jev", "openrouter"}:
                answer = result["answers"]["route"]
                choice = answer["choice"]
                confidence = answer["probabilities"][choice]
            else:
                answer = result["results"][0]
                choice = answer["decision"]["route"]
                confidence = answer["fields"]["route"]["probability"]
            if choice not in choices or not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise DecisionError("Backend returned a choice outside the allowed set")
            return Decision(choice, float(confidence), self.backend)
        except (KeyError, IndexError, TypeError, ValueError, OSError, TimeoutError, json.JSONDecodeError) as error:
            raise DecisionError(f"{self.backend} decision failed: {type(error).__name__}") from error


def selected_action(decision: Decision, actions: Mapping[str, dict], *, threshold: float) -> dict | None:
    """Return only a predeclared, exact host action, never model-generated arguments."""
    if not 0 <= threshold <= 1 or decision.confidence < threshold:
        return None
    action = actions.get(decision.choice)
    if not isinstance(action, dict) or not isinstance(action.get("tool_name"), str):
        return None
    arguments = action.get("tool_args", {})
    if not isinstance(arguments, dict) or not action["tool_name"]:
        return None
    return {"tool_name": action["tool_name"], "tool_args": arguments.copy()}
