"""Small A2A JSON-RPC client; no FastA2A response-model dependency."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from contextlib import contextmanager

from .formats import FormatError, dialect_from_card, encode_message, normalize_result


class A2AError(RuntimeError):
    pass


def payload(response):
    if not isinstance(response, dict):
        raise A2AError("Invalid A2A response object")
    if "error" in response:
        code = (response.get("error") or {}).get("code", "unknown")
        raise A2AError(f"A2A peer returned JSON-RPC error {code}")
    result = response.get("result", response)
    if not isinstance(result, dict):
        raise A2AError("Invalid A2A result")
    try:
        return normalize_result(result)
    except FormatError as exc:
        raise A2AError(str(exc)) from None


def context(result):
    return result.get("contextId") or result.get("context_id") or ""


def state(result):
    status = result.get("status") or {}
    value = status.get("state", "") if isinstance(status, dict) else status
    return str(value).removeprefix("TASK_STATE_").lower().replace("_", "-")


def message_text(message):
    if not isinstance(message, dict):
        return message.strip() if isinstance(message, str) else ""
    parts = message.get("parts") or []
    return "\n".join(p["text"].strip() for p in parts
                     if isinstance(p, dict) and isinstance(p.get("text"), str)
                     and p["text"].strip())


def reply_text(result):
    for artifact in reversed(result.get("artifacts") or []):
        if text := message_text(artifact):
            return text
    for message in reversed(result.get("history") or []):
        if isinstance(message, dict) and message.get("role") in ("user", "ROLE_USER"):
            continue
        if text := message_text(message):
            return text
    status = result.get("status") or {}
    if isinstance(status, dict) and (text := message_text(status.get("message"))):
        return text
    if result.get("role") in ("user", "ROLE_USER"):
        return ""
    return message_text(result)


class Client:
    def __init__(self, url, token, timeout=180, transport=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise A2AError("Configure a valid A2A peer HTTP or HTTPS endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise A2AError("A2A peer endpoint must not contain credentials or query parameters")
        if token == "":
            raise A2AError("A2A peer bearer credential is not configured")
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = min(max(int(timeout), 5), 600)
        self.transport = transport or self._http
        self.dialect = None

    def _http(self, method, url, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token is not None:
            headers["Authorization"] = "Bearer " + self.token
        if method == "POST" and self.dialect:
            headers["A2A-Version"] = self.dialect
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            raise A2AError(f"A2A peer HTTP {exc.code}") from None
        except (OSError, urllib.error.URLError) as exc:
            raise A2AError(f"A2A peer connection failed ({type(exc).__name__})") from None
        if len(raw) > 4 * 1024 * 1024:
            raise A2AError("A2A peer response exceeds the supported size")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise A2AError("A2A peer returned invalid JSON") from None

    def rpc(self, method, params):
        return payload(self.transport("POST", self.url + "/", {
            "jsonrpc": "2.0", "id": uuid.uuid4().hex,
            "method": method, "params": params}))

    def converse(self, message, context_id, save_context):
        try:
            card = self.transport("GET", self.url + "/.well-known/agent-card.json")
        except A2AError as exc:
            if str(exc) != "A2A peer HTTP 404":
                raise
            card = self.transport("GET", self.url + "/.well-known/agent.json")
        try:
            self.dialect = dialect_from_card(card)
        except FormatError as exc:
            raise A2AError(str(exc)) from None
        version_one = self.dialect == "1.0"
        ctx = context_id or "ctx-" + uuid.uuid4().hex
        msg = encode_message({"role": "user", "messageId": uuid.uuid4().hex,
                              "contextId": ctx, "parts": [{"kind": "text", "text": message}]}, self.dialect)
        if version_one:
            method, get_method = "SendMessage", "GetTask"
        else:
            method, get_method = "message/send", "tasks/get"
        params = {"message": msg, "configuration": {"blocking": True, "acceptedOutputModes": ["text/plain"]}}
        # Never resend on parsing/poll errors: a send can already have run the remote agent.
        result = self.rpc(method, params)
        deadline = time.monotonic() + self.timeout
        while True:
            ctx = context(result) or ctx
            save_context(ctx)
            task_state = state(result)
            if task_state in ("failed", "canceled", "cancelled", "rejected", "auth-required"):
                raise A2AError("A2A peer task ended: " + task_state)
            text = reply_text(result)
            if task_state in ("completed", "input-required") or (
                    not task_state and text and "parts" in result):
                if not text:
                    raise A2AError("A2A peer returned no assistant text")
                return {"text": text, "context_id": ctx, "state": task_state or "completed"}
            if not result.get("id"):
                raise A2AError("A2A peer returned neither a finished reply nor a task ID")
            if time.monotonic() >= deadline:
                raise A2AError("A2A peer task is still pending; context was preserved")
            time.sleep(1)
            result = self.rpc(get_method, {"id": result["id"]})


@contextmanager
def _conversation_lock(path):
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def converse_persisted(client, message, state_dir, reset=False):
    """Serialize calls and persist one context per configured endpoint across chats."""
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    with _conversation_lock(root / "conversation.lock"):
        path = root / "conversation.json"
        if path.exists():
            try:
                saved = json.loads(path.read_text())
            except ValueError:
                raise A2AError("Saved A2A peer context is invalid; refusing to silently reset") from None
        else:
            saved = {}
        contexts = saved.get("contexts", {})
        ctx = "" if reset else contexts.get(client.url, "")

        def save(value):
            contexts[client.url] = value
            temporary = root / "conversation.json.tmp"
            temporary.write_text(json.dumps({"contexts": contexts}))
            os.replace(temporary, path)

        return client.converse(message, ctx, save)
