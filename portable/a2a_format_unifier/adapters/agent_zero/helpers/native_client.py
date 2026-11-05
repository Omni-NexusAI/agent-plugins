"""Plugin-local native-first parser fallback; never chooses a destination."""
import inspect
import json
from urllib.parse import urlsplit

from .credentials import resolve_credential
from .fallback import adapt_rejected_reply, is_agent_zero


def _endpoint(url):
    try:
        value = urlsplit(url if "://" in url else "http://" + url)
        port = value.port or (443 if value.scheme == "https" else 80)
    except (ValueError, TypeError):
        return None
    if value.scheme not in ("http", "https") or not value.hostname or value.username or value.password or value.query or value.fragment:
        return None
    return (value.scheme.lower(), (value.hostname or "").lower(),
            port, value.path.rstrip("/"))


def configured_endpoint(config, url):
    target = _endpoint(url)
    matches = [entry for entry in config.get("endpoints", [])
               if isinstance(entry, dict) and target is not None and _endpoint(str(entry.get("url", ""))) == target]
    if len(matches) > 1:
        raise RuntimeError("Duplicate explicit A2A endpoint configuration")
    return matches[0] if matches else None


class NativeReplyFallback:
    def __init__(self, native, connection, enabled):
        self.native = native
        self.connection = connection
        self.enabled = enabled
        self.last_response = None

    def __getattr__(self, name):
        return getattr(self.native, name)

    async def capture(self, response):
        # Keep the response object, without reading or altering native I/O.
        self.last_response = response

    async def _call(self, method, validator, *args, **kwargs):
        from pydantic import ValidationError
        self.last_response = None
        try:
            return await getattr(self.native, method)(*args, **kwargs)
        except ValidationError:
            card = self.connection._agent_card
            received = self.last_response
            if not self.enabled() or not card or is_agent_zero(card) or received is None:
                raise
            if received.request.method != "POST" or received.status_code != 200:
                raise
            if _endpoint(str(received.request.url)) != _endpoint(self.connection.agent_url):
                raise
            raw = received.json()
            request = json.loads(received.request.content)
            if not isinstance(raw, dict) or raw.get("id") != request.get("id"):
                raise
            # The send already happened. Adapt that exact reply, never resend.
            return adapt_rejected_reply(raw, card, validator)

    async def send_message(self, *args, **kwargs):
        from fasta2a.client import send_message_response_ta
        return await self._call("send_message", send_message_response_ta.validate_python, *args, **kwargs)

    async def get_task(self, *args, **kwargs):
        from fasta2a.client import get_task_response_ta
        return await self._call("get_task", get_task_response_ta.validate_python, *args, **kwargs)


def install():
    from pathlib import Path
    from helpers.fasta2a_client import AgentConnection
    import fasta2a.client as client_module
    original_init = AgentConnection.__init__
    original_card = AgentConnection.get_agent_card
    if getattr(original_init, "_a2a_format_fallback", False):
        return False
    if not inspect.iscoroutinefunction(original_card):
        raise RuntimeError("Unsupported native A2A client interface")
    if not all(hasattr(client_module, name) for name in ("send_message_response_ta", "get_task_response_ta")):
        raise RuntimeError("Unsupported native A2A response validators")

    def settings():
        from helpers.plugins import get_enabled_plugins, get_plugin_config
        if "a2a_format_unifier" not in get_enabled_plugins(None):
            return None
        config = get_plugin_config("a2a_format_unifier") or {}
        return config if config.get("outbound_fallback", True) else None

    def initialize(self, agent_url, timeout=30, token=None):
        original_init(self, agent_url, timeout=timeout, token=token)
        config = settings()
        if config is None:
            return
        entry = configured_endpoint(config, self.agent_url)
        if entry and str(entry.get("framework", "")).lower() in ("agent-zero", "agent_zero", "a0"):
            entry = None
        if entry and token is None:
            credential = resolve_credential(entry, Path(__file__).resolve().parents[1])
            if credential:
                self._http_client.headers["Authorization"] = "Bearer " + credential
                self._http_client.headers.pop("X-API-KEY", None)
        fallback = NativeReplyFallback(self._a2a_client, self, lambda: settings() is not None)
        self._a2a_client = fallback
        self._a2a_format_fallback = fallback
        self._a2a_expected_name = (entry or {}).get("expected_agent_name")
        self._http_client.event_hooks.setdefault("response", []).append(fallback.capture)

    async def card(self):
        try:
            result = await original_card(self)
        except RuntimeError:
            fallback = getattr(self, "_a2a_format_fallback", None)
            received = fallback.last_response if fallback else None
            if settings() is None or received is None or received.status_code != 404:
                raise
            # A read-only card alias retry, at the original destination only.
            response = await self._http_client.get(self.agent_url + "/.well-known/agent-card.json")
            response.raise_for_status()
            result = response.json()
            self._agent_card = result
        expected = getattr(self, "_a2a_expected_name", None)
        if expected and result.get("name") != expected:
            self._agent_card = None
            raise RuntimeError("A2A card identity does not match the explicitly configured endpoint")
        return result

    initialize._a2a_format_fallback = True
    initialize._a2a_original = original_init
    card._a2a_original = original_card
    AgentConnection.__init__ = initialize
    AgentConnection.get_agent_card = card
    return True
