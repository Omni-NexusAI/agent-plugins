"""Scripted OpenAI-compatible stub model for the isolated Looped Mode tests.

Standard library only. It replays a scenario's responses in order, so a test
is deterministic and needs no real model and no GPU.

  POST /v1/chat/completions   scripted reply (streaming or not)
  POST /v1/embeddings         zero vectors
  GET  /v1/models             one fake model
  POST /__admin/scenario      load {"main": [...], "plan": [...], "default": "..."}
  GET  /__admin/log           calls seen so far and replies left

A call is "main" when its system prompt describes the agent's tool format,
"plan" when it is a looped-mode planning call, and "other" otherwise (chat
naming and similar utility calls), which gets the default reply.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EXHAUSTED = json.dumps({
    "thoughts": ["The stub has no scripted reply left."],
    "headline": "Stub exhausted",
    "tool_name": "response",
    "tool_args": {"text": "[stub exhausted]"},
})

_lock = threading.Lock()
_state = {"main": [], "plan": [], "default": "ok", "log": []}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def classify(messages: list) -> str:
    system = "\n".join(_text(m.get("content")) for m in messages
                       if isinstance(m, dict) and m.get("role") == "system")
    if system.startswith("You are planning") or system.startswith("You are given independent plans"):
        return "plan"
    if "tool_name" in system and "tool_args" in system:
        return "main"
    return "other"


def next_reply(body: dict) -> str:
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    kind = classify(messages)
    last = _text(messages[-1].get("content")) if messages and isinstance(messages[-1], dict) else ""
    whole = "\n".join(_text(m.get("content")) for m in messages if isinstance(m, dict))
    with _lock:
        queue = _state.get(kind) if kind in ("main", "plan") else None
        if queue:
            reply = queue.pop(0)
        elif kind == "main":
            reply = EXHAUSTED
        elif kind == "plan":
            reply = "1. Do the task."
        else:
            reply = _state["default"]
        _state["log"].append({
            "kind": kind,
            "stream": bool(body.get("stream")),
            "seed": body.get("seed"),
            "temperature": body.get("temperature"),
            "messages": len(messages),
            "reread": "Read the task again" in whole,
            "retry_note": "The previous step failed" in whole,
            "plan_note": "Plan merged from independent planning passes" in whole,
            "fuse": last.startswith("Two independent drafts"),
            "deepen": last.startswith("This is your first-pass draft"),
            "slash_token": "/looped" in whole,
            "scripted": bool(queue is not None and reply is not EXHAUSTED),
            "time": time.time(),
        })
    return reply if isinstance(reply, str) else json.dumps(reply)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep container logs quiet
        return

    def _json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            value = {}
        return value if isinstance(value, dict) else {}

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path.endswith("/models"):
            return self._json({"object": "list", "data": [
                {"id": "stub-model", "object": "model", "owned_by": "looped-test"}]})
        if path == "/__admin/log":
            with _lock:
                return self._json({"log": list(_state["log"]),
                                   "main_left": len(_state["main"]),
                                   "plan_left": len(_state["plan"])})
        if path in ("", "/health"):
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        body = self._body()
        if path == "/__admin/scenario":
            with _lock:
                _state["main"] = list(body.get("main") or [])
                _state["plan"] = list(body.get("plan") or [])
                _state["default"] = str(body.get("default") or "ok")
                _state["log"] = []
            return self._json({"ok": True})
        if path.endswith("/embeddings"):
            items = body.get("input")
            count = len(items) if isinstance(items, list) else 1
            return self._json({"object": "list", "model": "stub-embed", "data": [
                {"object": "embedding", "index": index, "embedding": [0.0] * 8}
                for index in range(count)], "usage": {"prompt_tokens": 0, "total_tokens": 0}})
        if path.endswith("/chat/completions"):
            return self._chat(body)
        return self._json({"error": "not found"}, 404)

    def _chat(self, body: dict):
        reply = next_reply(body)
        base = {"id": "chatcmpl-stub", "created": int(time.time()),
                "model": body.get("model") or "stub-model"}
        if not body.get("stream"):
            return self._json({**base, "object": "chat.completion", "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": reply}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        size = max(1, len(reply) // 4)
        pieces = [reply[index:index + size] for index in range(0, len(reply), size)] or [""]
        try:
            for index, piece in enumerate(pieces):
                delta = {"content": piece}
                if index == 0:
                    delta["role"] = "assistant"
                self._event({**base, "object": "chat.completion.chunk", "choices": [
                    {"index": 0, "delta": delta, "finish_reason": None}]})
            self._event({**base, "object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}]})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the agent stops reading once a complete tool call has arrived
        self.close_connection = True

    def _event(self, payload):
        self.wfile.write(b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n")
        self.wfile.flush()


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    host = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"looped-test stub model listening on {port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
