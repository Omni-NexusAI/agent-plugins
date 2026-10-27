"""Framework-independent ASGI adapter for a legacy A2A JSON-RPC server.

Authentication remains in the wrapped server. Only supported v1 method names
and response bodies are translated; no alternate listener or auth path exists.
"""
import asyncio
import json
import time
from datetime import datetime
from urllib.parse import urlsplit

from .formats import FormatError, normalize_message, normalize_result, encode_message, encode_result


class LegacyServerUnifier:
    METHODS = {"SendMessage": "message/send", "GetTask": "tasks/get", "CancelTask": "tasks/cancel"}
    LIMIT = 4 * 1024 * 1024

    def __init__(self, app, poll_timeout=90, poll_interval=1, legacy_timezone=None):
        self.app = app
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval
        self.legacy_timezone = legacy_timezone

    @staticmethod
    def supports_scope(scope):
        """Opt in only for the modern card alias or explicit v1 requests."""
        if scope.get("type") != "http":
            return False
        if scope.get("method") == "GET":
            return scope.get("path", "").endswith("/.well-known/agent-card.json")
        if scope.get("method") == "POST":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            version = headers.get(b"a2a-version", b"")
            return version == b"1.0" or version.startswith(b"1.0.")
        return False

    async def __call__(self, scope, receive, send):
        if not self.supports_scope(scope):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        card = scope.get("method") == "GET"
        response_scope = scope
        if card:
            # The legacy URL and its card remain entirely native. Only the
            # modern alias opts in to reachable-origin correction.
            scope = dict(scope)
            scope["path"] = path.removesuffix("agent-card.json") + "agent.json"
            if scope.get("raw_path"):
                scope["raw_path"] = scope["path"].encode()
        method = None
        request_id = None
        if scope.get("method") == "POST":
            chunks = bytearray()
            while True:
                event = await receive()
                if event.get("type") != "http.request":
                    return
                chunks.extend(event.get("body", b""))
                if len(chunks) > self.LIMIT:
                    return await self._error(send, 413, None, "A2A request is too large")
                if not event.get("more_body"):
                    break
            body = bytes(chunks)
            try:
                request = json.loads(body)
                if isinstance(request, dict) and request.get("method") in self.METHODS:
                    method = request["method"]
                    request_id = request.get("id")
                    params = request.setdefault("params", {})
                    if not isinstance(params, dict):
                        raise FormatError("A2A params must be an object")
                    if method == "SendMessage":
                        params["message"] = encode_message(normalize_message(params["message"]), "0.3")
                        configuration = params.setdefault("configuration", {})
                        configuration["blocking"] = True
                        configuration.setdefault("acceptedOutputModes", ["text/plain"])
                    request["method"] = self.METHODS[method]
                    body = json.dumps(request).encode()
            except (ValueError, KeyError, TypeError):
                # Let the native server validate malformed or unsupported input.
                method = None

            first = True
            original_receive = receive

            async def replay():
                nonlocal first
                if first:
                    first = False
                    return {"type": "http.request", "body": body, "more_body": False}
                return await original_receive()

            receive = replay
            if method:
                scope = dict(scope)
                scope["headers"] = [(k, v) for k, v in scope.get("headers", [])
                                    if k.lower() not in (b"content-length", b"a2a-version")]

        if not method and not card:
            return await self.app(scope, receive, send)
        start = None
        chunks = bytearray()

        async def collect(event):
            nonlocal start
            if event["type"] == "http.response.start":
                start = dict(event)
            elif event["type"] == "http.response.body":
                chunks.extend(event.get("body", b""))
                if len(chunks) > self.LIMIT:
                    raise FormatError("A2A response too large")

        try:
            await self.app(scope, receive, collect)
            if method == "SendMessage" and start and 200 <= start["status"] < 300:
                deadline = time.monotonic() + self.poll_timeout
                while True:
                    response = json.loads(bytes(chunks))
                    result = response.get("result", {})
                    status = result.get("status", {}) if isinstance(result, dict) else {}
                    if status.get("state") not in ("submitted", "working") or not result.get("id"):
                        break
                    if time.monotonic() >= deadline:
                        return await self._error(send, 504, request_id, "A2A task is still pending; do not resend the message")
                    await asyncio.sleep(self.poll_interval)
                    poll = json.dumps({"jsonrpc": "2.0", "id": request_id,
                                       "method": "tasks/get", "params": {"id": result["id"]}}).encode()

                    async def poll_receive():
                        return {"type": "http.request", "body": poll, "more_body": False}

                    chunks.clear()
                    start = None
                    await self.app(scope, poll_receive, collect)
                    if not start or not 200 <= start["status"] < 300:
                        break
        except (ValueError, TypeError, AttributeError):
            return await self._error(send, 502, request_id, "Unsupported A2A response format")
        if start is None:
            return await self._error(send, 502, request_id, "Missing A2A response")
        output = bytes(chunks)
        # In particular: do not alter authentication failures or server errors.
        if 200 <= start["status"] < 300:
            try:
                response = json.loads(output)
                if card:
                    endpoint = self._endpoint(response_scope)
                    if endpoint:
                        response["url"] = endpoint
                elif isinstance(response, dict) and "result" in response:
                    legacy = normalize_result(response["result"])
                    status = legacy.get("status", {})
                    timestamp = status.get("timestamp")
                    if timestamp and self.legacy_timezone is not None:
                        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            status["timestamp"] = parsed.replace(tzinfo=self.legacy_timezone).isoformat()
                    if not status.get("message"):
                        for message in reversed(legacy.get("history") or []):
                            if message.get("role") == "agent":
                                status["message"] = message
                                break
                    result = encode_result(legacy, "1.0")
                    response["result"] = result if method == "SendMessage" else result.get("task", result.get("message", result))
                output = json.dumps(response).encode()
            except (ValueError, TypeError):
                if method:
                    return await self._error(send, 502, request_id, "Unsupported A2A response format")
        start["headers"] = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
        start["headers"].append((b"content-length", str(len(output)).encode()))
        await send(start)
        await send({"type": "http.response.body", "body": output, "more_body": False})

    @staticmethod
    def _endpoint(scope):
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("ascii", errors="ignore")
        scheme = scope.get("scheme", "http")
        parsed = urlsplit(scheme + "://" + host)
        if scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return None
        prefix = scope.get("path", "").split("/.well-known/", 1)[0]
        root = scope.get("root_path", "")
        if root and not (prefix == root or prefix.startswith(root + "/")):
            prefix = root.rstrip("/") + "/" + prefix.lstrip("/")
        return scheme + "://" + host + prefix.rstrip("/") + "/"

    @staticmethod
    async def _error(send, status, request_id, message):
        body = json.dumps({"jsonrpc": "2.0", "id": request_id,
                           "error": {"code": -32602, "message": message}}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})
