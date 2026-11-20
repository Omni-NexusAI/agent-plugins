"""Model clients for the benchmark: a real OpenAI-compatible one and a simulator."""

from __future__ import annotations

import asyncio
import json
import random
import urllib.request
from typing import Any


class OpenAIClient:
    """Minimal chat-completions client (standard library only)."""

    def __init__(self, endpoint: str, model: str, api_key: str = "", timeout: float = 600.0,
                 max_tokens: int = 2048, extra: dict[str, Any] | None = None,
                 pause: float = 0.0):
        self.endpoint = endpoint.rstrip("/")
        self.model, self.api_key, self.timeout = model, api_key, timeout
        self.max_tokens, self.extra = max_tokens, dict(extra or {})
        self.pause = max(0.0, pause)        # idle seconds after each request
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint + "/chat/completions",
                                         data=json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def complete(self, messages: list[dict[str, str]], *, temperature: float | None = None,
                       seed: int | None = None) -> tuple[str, str]:
        body: dict[str, Any] = {"model": self.model, "messages": messages,
                                "max_tokens": self.max_tokens, **self.extra}
        if temperature is not None:
            body["temperature"] = temperature
        if seed is not None:
            body["seed"] = seed
        reply = await asyncio.to_thread(self._post, body)
        if self.pause:
            await asyncio.sleep(self.pause)
        self.calls += 1
        usage = reply.get("usage") or {}
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        message = (reply.get("choices") or [{}])[0].get("message") or {}
        return message.get("content") or "", message.get("reasoning_content") or ""


class SimulatedModel:
    """A stand-in model for checking the pipeline. NOT evidence about any model.

    Each call answers a task correctly with probability ``skill`` (lowered for
    tasks marked hard), otherwise it gives a plausible wrong step, and with
    probability ``malformed`` it emits no JSON at all. A re-read prompt adds
    ``reread_gain`` to the skill. Errors are independent between calls, which is
    the best case for agreement between passes: real models repeat their
    mistakes, so real gains will be smaller.
    """

    def __init__(self, gold: dict[str, Any], skill: float = 0.7, malformed: float = 0.05,
                 reread_gain: float = 0.03, seed: int = 0):
        self.gold, self.skill, self.malformed = gold, skill, malformed
        self.reread_gain = reread_gain
        self.rng = random.Random(seed)
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def complete(self, messages: list[dict[str, str]], *, temperature: float | None = None,
                       seed: int | None = None) -> tuple[str, str]:
        self.calls += 1
        question = next(m["content"] for m in messages if m["role"] == "user")
        task = self.gold[question]
        text = "\n".join(m["content"] for m in messages)
        self.prompt_tokens += len(text) // 4
        if self.rng.random() < self.malformed:
            return "I think the answer is clear, so I will just say it.", ""
        hard = sum(map(ord, task.id)) % 5 == 0      # stable across runs, unlike hash()
        skill = self.skill * (0.6 if hard else 1.0)
        if "Read the task again" in text:
            skill += self.reread_gain
        correct = self.rng.random() < skill
        if task.kind == "tool":
            name, args = task.tool_name, dict(task.tool_args)
            if not correct:
                if self.rng.random() < 0.5:
                    name = self.rng.choice(["read_file", "write_file", "run_shell", "search_web"])
                else:
                    key = self.rng.choice(sorted(args))
                    args[key] = str(args[key]) + self.rng.choice(["_old", "s", " copy"])
        else:
            name = "response"
            answer = task.answer
            if not correct:
                answer = (str(int(answer) + self.rng.choice([-10, -1, 1, 10, 100]))
                          if answer.lstrip("-").isdigit() else answer + "?")
            args = {"text": answer}
        reply = json.dumps({"thoughts": ["simulated"], "headline": "step",
                            "tool_name": name, "tool_args": args})
        self.completion_tokens += len(reply) // 4
        return reply, ""
