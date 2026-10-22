"""Server-side discovery of models (and router configurations) on local inference endpoints.

Layered ON TOP of Agent Zero's own model search; never replaces it. GET only, with these guarantees
(pinned by tests/test_endpoint_discovery.py and written down in AGENTS.md):

* the endpoint's host is resolved first and classified: loopback, RFC1918/ULA and CGNAT (Tailscale) addresses
  are probed; link-local, cloud-metadata, unspecified and multicast addresses are refused; public hosts are
  skipped (the host's own search covers cloud providers). The connection goes to a checked address, never to
  a second DNS answer.
* no redirects, no query string, http(s) only, 2 MiB response cap, at most 3 requests per call at 4 s each.
* the API key is the FIRST stored key only (never advancing the host's multi-key round robin) and is sent only
  to a host that passed the check.
* no model load/unload/reload request is ever made; error messages are fixed strings (never response bodies).
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import ipaddress
import json
import re
import socket
import ssl
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

PLUGIN_NAME = "provider_profiles"
USER_AGENT = "provider-profiles-discovery/1"
REQUEST_TIMEOUT = 4.0
DNS_TIMEOUT = 4.0
CALL_TIMEOUT = 10.0
MAX_REQUESTS = 3
MAX_PINS = 2
MAX_BYTES = 2 * 1024 * 1024
CACHE_TTL = 15.0
MAX_CACHE = 64
PLACEHOLDER_KEYS = {"", "none", "null", "lm-studio", "llama-cpp", "omlx", "vllm", "ollama"}
PROVIDER_ID = re.compile(r"[a-z0-9_]{1,64}")


def _sibling(name: str):
    try:
        return importlib.import_module(f"usr.plugins.{PLUGIN_NAME}.helpers.{name}")
    except Exception:  # noqa: BLE001 - path-based fallback (files execute without package context)
        path = Path(__file__).resolve().parent / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"_provider_profiles_{name}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


parsers = _sibling("endpoint_parsers")


# ---------------------------------------------------------------- errors
class DiscoveryError(Exception):
    def __init__(self, category: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.hint = hint

    def as_dict(self) -> dict:
        return {"category": self.category, "message": self.message, "hint": self.hint}


def _error(category: str, display: str = "", provider: str = "", status: int | None = None) -> DiscoveryError:
    """Every message is a fixed string built from the host:port, the provider id and a status code only."""
    local_name = display.rsplit(":", 1)[0].strip("[]") in ("localhost", "127.0.0.1", "::1")
    unreachable_hint = ("Inside Docker, localhost is the container itself: use host.docker.internal or the machine's LAN/Tailscale address."
                        if local_name else "Check that the server is running and listens on an address this machine can reach (for example 0.0.0.0).")
    table = {
        "unreachable": (f"Could not connect to {display}.", unreachable_hint),
        "dns": (f"Could not resolve the host of {display}.", "Check the host name in the API base URL."),
        "timeout": (f"No answer from {display} within {int(REQUEST_TIMEOUT)} seconds.", "The server may be busy loading a model; try again."),
        "tls": (f"The TLS certificate of {display} is not trusted.",
                "If the server uses a private CA, add it to Agent Zero's trust store (SSL_CERT_FILE)."),
        "tls_protocol": (f"{display} did not complete a TLS handshake.", "Check whether the server speaks https:// or plain http:// on this port."),
        "unauthorized": (f"{display} requires an API key.",
                         f"Save the API key for provider \"{provider}\" in Agent Zero's API keys; keys that are typed but not saved are never sent."),
        "forbidden": (f"{display} refused this client (HTTP 403).", "Check the server's allowed hosts, origins and key permissions."),
        "not_found": (f"No model list was found at {display}.", "Check the API base URL (it usually ends with /v1)."),
        "bad_payload": (f"{display} answered, but not with a usable model list.", "Check that the API base points at an OpenAI-compatible server."),
        "redirect": (f"{display} redirected the request.", "Use the final address as the API base (for example https:// instead of http://)."),
        "server_error": (f"{display} answered with HTTP {status}." if status else f"{display} answered with a server error.",
                         "The server is rate limiting requests; try again shortly." if status == 429
                         else "Check the server's log." if not status or status >= 500
                         else "Check the API base URL and whether the server expects https://."),
        "blocked": (f"Discovery will not probe {display}.", "Link-local, cloud-metadata and unspecified addresses are never contacted."),
        "invalid_base": ("The API base URL is not usable for discovery.", "It must be an http(s) URL without credentials, query string or fragment."),
    }
    message, hint = table[category]
    return DiscoveryError(category, message, hint)


# ---------------------------------------------------------------- address policy
_METADATA = {ipaddress.ip_address(a) for a in ("169.254.169.254", "169.254.170.2", "100.100.100.200", "192.0.0.192", "fd00:ec2::254")}
_PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")]
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def classify_address(value: str) -> str:
    """'loopback' | 'private' | 'cgnat' | 'blocked' | 'public' for one IP literal."""
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return "blocked"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip in _METADATA or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return "blocked"
    if ip.is_loopback:  # before is_reserved: Python lists ::1 inside the reserved ::/8
        return "loopback"
    if any(ip in net for net in _PRIVATE_NETS):
        return "private"
    if ip in _CGNAT:
        return "cgnat"
    return "blocked" if ip.is_reserved else "public"


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


async def default_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in seen:
            seen.append(address)
    return seen


async def classify_host(host: str, port: int, resolver=default_resolver) -> tuple[str, list[str]]:
    """('local' | 'blocked' | 'public' | 'unresolved', addresses). Only a fully local answer is probed."""
    if _is_ip_literal(host):
        addresses = [host]
    else:
        try:
            addresses = list(await asyncio.wait_for(resolver(host, port), DNS_TIMEOUT))
        except (OSError, UnicodeError, asyncio.TimeoutError, TimeoutError):
            return "unresolved", []
    if not addresses:
        return "unresolved", []
    classes = [classify_address(a) for a in addresses]
    if "blocked" in classes:
        return "blocked", addresses
    if all(c in ("loopback", "private", "cgnat") for c in classes):
        return "local", addresses
    return "public", addresses


def _order_pins(addresses: list[str]) -> list[str]:
    """IPv4 first (local servers bind IPv4 far more often), at most MAX_PINS addresses."""
    return ([a for a in addresses if ":" not in a] + [a for a in addresses if ":" in a])[:MAX_PINS]


# ---------------------------------------------------------------- API key
def clean_key(raw: Any) -> str | None:
    """First comma-separated key; 'None', placeholder and non-header-safe keys mean 'no key'."""
    if not isinstance(raw, str):
        return None
    first = raw.split(",")[0].strip()
    if first.lower() in PLACEHOLDER_KEYS or not (first.isascii() and first.isprintable()):
        return None
    return first


# ---------------------------------------------------------------- base URL
def parse_base(base: Any) -> dict:
    text = str(base or "").strip()
    if not text or "\\" in text or any(ord(c) <= 32 or ord(c) == 127 for c in text) or "?" in text or "#" in text:
        raise _error("invalid_base")
    try:
        parts = urlsplit(text)
        host = parts.hostname
        port = parts.port
    except ValueError as error:
        raise _error("invalid_base") from error
    if parts.scheme not in ("http", "https") or not host or parts.username is not None or parts.password is not None \
            or parts.query or parts.fragment or port == 0:
        raise _error("invalid_base")
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise _error("invalid_base") from error
    port = port if port is not None else (443 if parts.scheme == "https" else 80)
    stack: list[str] = []
    for segment in parts.path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if stack:
                stack.pop()
            continue
        stack.append(segment)
    path = ("/" + "/".join(stack)) if stack else ""
    if path.lower().endswith("/v1"):
        path = path[:-3]
    shown = f"[{host}]" if ":" in host else host
    return {"scheme": parts.scheme, "host": host.lower(), "port": port, "path": path, "display": f"{shown}:{port}"}


# ---------------------------------------------------------------- probe plans
def probe_plan(provider: str) -> list[str]:
    """Ordered discovery steps (at most MAX_REQUESTS requests are issued per call, enrichment included)."""
    hint = (provider or "").lower()
    if hint == "ollama":
        return ["ollama_tags", "openai", "models_root"]
    if hint == "lm_studio":
        return ["lmstudio_v1", "lmstudio_v0", "openai"]
    return ["openai", "models_root", "lmstudio_v1"]


_STEP_PATHS = {
    "openai": "/v1/models", "models_root": "/models", "lmstudio_v1": "/api/v1/models", "lmstudio_v0": "/api/v0/models",
    "ollama_tags": "/api/tags", "ollama_ps": "/api/ps", "props": "/props", "status": "/status",
}
# a second, read-only request that adds loaded state / served context to what the list already returned
_ENRICHMENT = {"ollama": ("ollama_ps", "merge_ollama_ps"), "llama_cpp": ("props", "merge_llamacpp_props"),
               "strata_router": ("status", "merge_strata_status")}


# ---------------------------------------------------------------- HTTP
class _BadBody(Exception):
    """Oversized or non-JSON body (mapped to the bad_payload category)."""


_TLS_CONTEXT: ssl.SSLContext | None = None


def _tls_context() -> ssl.SSLContext:
    """Same trust as the host's own httpx calls: certifi, or SSL_CERT_FILE / SSL_CERT_DIR when set."""
    global _TLS_CONTEXT
    if _TLS_CONTEXT is None:
        _TLS_CONTEXT = httpx.create_ssl_context(verify=True, trust_env=True)
    return _TLS_CONTEXT


def make_client(scheme: str) -> httpx.AsyncClient:
    """No redirects and no proxy/env trust: the request must reach exactly the address that was checked."""
    return httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT), follow_redirects=False, trust_env=False,
                             verify=_tls_context() if scheme == "https" else False,
                             headers={"User-Agent": USER_AGENT, "Accept": "application/json"})


def _map_exception(exc: BaseException, display: str) -> DiscoveryError:
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return _error("timeout", display)
    cause: BaseException | None = exc
    for _ in range(6):
        if isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(cause):
            return _error("tls", display)
        if isinstance(cause, ssl.SSLError):
            return _error("tls_protocol", display)
        cause = (cause.__cause__ or cause.__context__) if cause is not None else None
        if cause is None:
            break
    return _error("unreachable", display)


def _bracket(host: str) -> str:
    return f"[{host}]" if ":" in host else host


async def _get_json(client: httpx.AsyncClient, base: dict, pin: str | None, path: str, headers: dict) -> tuple[int, Any]:
    """One GET. Returns (status, payload-or-None); raises DiscoveryError for transport failures and bad bodies."""
    display = base["display"]
    url = f"{base['scheme']}://{_bracket(pin or base['host'])}:{base['port']}{base['path']}{path}"
    default_port = 443 if base["scheme"] == "https" else 80
    request_headers = dict(headers)
    request_headers["Host"] = _bracket(base["host"]) if base["port"] == default_port else f"{_bracket(base['host'])}:{base['port']}"
    # connect to the checked address, but verify the certificate and send SNI for the name the user entered
    extensions = {"sni_hostname": base["host"]} if base["scheme"] == "https" and pin else None

    async def fetch() -> tuple[int, Any]:
        async with client.stream("GET", url, headers=request_headers, extensions=extensions) as response:
            if response.status_code != 200:
                return response.status_code, None
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_BYTES:
                raise _BadBody
            chunks, total = [], 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise _BadBody
                chunks.append(chunk)
        try:
            return 200, json.loads(b"".join(chunks))
        except ValueError as error:
            raise _BadBody from error

    try:
        return await asyncio.wait_for(fetch(), REQUEST_TIMEOUT + 0.5)
    except _BadBody as error:
        raise _error("bad_payload", display) from error
    except Exception as exc:  # noqa: BLE001 - mapped to a fixed, body-free category
        raise _map_exception(exc, display) from exc


class _Session:
    """One discovery call: a client, the checked addresses to try, the auth headers and a request counter."""

    def __init__(self, client: httpx.AsyncClient, base: dict, pins: list[str | None], headers: dict):
        self.client, self.base, self.pins, self.headers = client, base, list(pins), headers
        self.requests = 0

    async def get(self, path: str) -> tuple[int, Any]:
        self.requests += 1
        for index, pin in enumerate(self.pins):
            try:
                result = await _get_json(self.client, self.base, pin, path, self.headers)
            except DiscoveryError as error:
                if error.category == "unreachable" and index < len(self.pins) - 1:
                    continue  # the next checked address of the same host
                raise
            self.pins = [pin]
            return result
        raise _error("unreachable", self.base["display"])  # no pins (cannot happen: callers pass at least [None])


def _is_empty_list(payload: Any) -> bool:
    if isinstance(payload, list):
        return not payload
    if isinstance(payload, dict):
        for key in ("data", "models"):
            if isinstance(payload.get(key), list):
                return not payload[key]
    return False


def _parse_step(step: str, payload: Any) -> tuple[str, list]:
    if step in ("openai", "models_root"):
        return parsers.parse_openai_models(payload)
    if step == "lmstudio_v1":
        return parsers.parse_lmstudio_v1(payload)
    if step == "lmstudio_v0":
        return parsers.parse_lmstudio_v0(payload)
    return parsers.parse_ollama_tags(payload)


async def discover(session: _Session, provider: str) -> dict:
    """Run the probe plan. Returns {'kind', 'entries', 'requests'} or raises DiscoveryError."""
    display = session.base["display"]
    kind, entries, last_error = None, [], None
    for step in probe_plan(provider):
        if session.requests >= MAX_REQUESTS:
            break
        try:
            status, payload = await session.get(_STEP_PATHS[step])
        except DiscoveryError as error:
            if error.category != "bad_payload":
                raise
            last_error = error
            continue
        if status == 200:
            step_kind, step_entries = _parse_step(step, payload)
            if step_entries:
                kind, entries = step_kind, step_entries
                break
            if _is_empty_list(payload):  # a valid, empty list is an answer (nothing downloaded yet), not an error
                return {"kind": step_kind, "entries": [], "requests": session.requests}
            last_error = _error("bad_payload", display)
            continue
        if status == 401:
            raise _error("unauthorized", display, provider)
        if status == 403:
            raise _error("forbidden", display)
        if 300 <= status < 400:
            raise _error("redirect", display)
        last_error = _error("not_found", display) if status in (404, 405, 410) else _error("server_error", display, status=status)
    if kind is None:
        raise last_error or _error("not_found", display)

    extra = _ENRICHMENT.get(kind)
    if extra and session.requests < MAX_REQUESTS:
        step, merge = extra
        try:
            status, payload = await session.get(_STEP_PATHS[step])
        except DiscoveryError:
            status, payload = 0, None  # enrichment is best effort: the list itself already succeeded
        if status == 200:
            entries = getattr(parsers, merge)(entries, payload)
    return {"kind": kind, "entries": entries, "requests": session.requests}


# ---------------------------------------------------------------- cache (successes only)
_cache: dict[tuple, tuple[float, dict]] = {}


def clear_cache() -> None:
    _cache.clear()


def _cache_key(base: dict, provider: str, api_key: str | None) -> tuple:
    family = provider if provider in ("ollama", "lm_studio") else "generic"
    fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:12] if api_key else ""
    return base["scheme"], base["host"], base["port"], base["path"], family, fingerprint


def _remember(key: tuple, now: float, result: dict) -> None:
    try:
        while len(_cache) >= MAX_CACHE:
            _cache.pop(next(iter(_cache)))
    except (StopIteration, KeyError, RuntimeError):
        _cache.clear()  # concurrent eviction from another event loop: start over, it is only a cache
    _cache[key] = (now, result)


# ---------------------------------------------------------------- request handling
def _response(*, ok: bool = True, skipped: str | None = None, endpoint: dict | None = None, entries: list | None = None,
              error: dict | None = None) -> dict:
    return {"ok": ok, "skipped": skipped, "endpoint": endpoint, "entries": entries or [], "error": error}


def _failure(error: DiscoveryError, display: str | None = None) -> dict:
    endpoint = {"kind": None, "label": None, "host": display, "requests": 0, "cached": False} if display else None
    return _response(error=error.as_dict(), endpoint=endpoint)


async def handle(payload: Any, *, settings: dict, provider_config: Callable[[str, str], Any],
                 stored_key: Callable[[str], Any], resolver=default_resolver, client_factory=make_client,
                 clock: Callable[[], float] = time.monotonic) -> dict:
    """Entry point used by api/discover_models.py (all host access is injected, so tests need no Agent Zero)."""
    if not isinstance(payload, dict):
        return _response(ok=False, error={"category": "invalid_request", "message": "The request body must be an object.", "hint": None})
    if not settings.get("discovery_enabled", True):
        return _response(skipped="disabled")
    provider = str(payload.get("provider") or "").strip().lower()
    if not PROVIDER_ID.fullmatch(provider):
        return _response(skipped="no_provider")
    model_type = "embedding" if str(payload.get("model_type") or "").strip().lower() == "embedding" else "chat"

    try:  # same lookup as the host search: the type's config, with the chat config's models_list as fallback
        cfg = provider_config(model_type, provider) or {}
        if model_type != "chat" and not cfg.get("models_list"):
            chat_cfg = provider_config("chat", provider) or {}
            if chat_cfg.get("models_list"):
                cfg = {**cfg, "models_list": chat_cfg["models_list"]}
    except Exception:  # noqa: BLE001 - an unknown provider simply has no defaults
        cfg = {}
    kwargs = cfg.get("kwargs") if isinstance(cfg.get("kwargs"), dict) else {}
    models_list = cfg.get("models_list") if isinstance(cfg.get("models_list"), dict) else {}
    base_text = str(payload.get("api_base") or "").strip() or str(kwargs.get("api_base") or "").strip() or str(models_list.get("default_base") or "").strip()
    if not base_text:
        return _response(skipped="no_base")

    try:
        base = parse_base(base_text)
    except DiscoveryError as error:
        return _failure(error)
    display = base["display"]
    verdict, addresses = await classify_host(base["host"], base["port"], resolver)
    if verdict == "public":
        return _response(skipped="public_host")
    if verdict == "blocked":
        return _failure(_error("blocked", display), display)
    if verdict == "unresolved":
        return _failure(_error("dns", display), display)

    try:
        api_key = clean_key(stored_key(provider))
    except Exception:  # noqa: BLE001
        api_key = None
    cache_key = _cache_key(base, provider, api_key)
    now = clock()
    cached = _cache.get(cache_key)
    from_cache = bool(cached) and payload.get("refresh") is not True and now - cached[0] < CACHE_TTL
    if from_cache:
        result = cached[1]
    else:
        pins: list[str | None] = [None] if _is_ip_literal(base["host"]) else list(_order_pins(addresses))
        client = client_factory(base["scheme"])
        try:
            session = _Session(client, base, pins, {"Authorization": f"Bearer {api_key}"} if api_key else {})
            result = await asyncio.wait_for(discover(session, provider), CALL_TIMEOUT)
        except DiscoveryError as error:
            return _failure(error, display)
        except Exception as exc:  # noqa: BLE001
            return _failure(_map_exception(exc, display), display)
        finally:
            await client.aclose()
        _remember(cache_key, now, result)

    return _response(endpoint={"kind": result["kind"], "label": parsers.KIND_LABELS.get(result["kind"], result["kind"]), "host": display,
                               "requests": 0 if from_cache else result["requests"], "cached": from_cache},
                     entries=parsers.entries_for(result["entries"], model_type))
