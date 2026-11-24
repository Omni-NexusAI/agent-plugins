"""Thin client for Agent Zero's built-in Remote Control (tunnel) system.

This plugin does NOT spawn its own tunnel processes. It drives the existing
remote-control machinery: the tunnel API server (run_tunnel.py) that the WebUI
"Remote Control" settings panel talks to via /tunnel_proxy. That keeps the URL,
provider, and running state shared with the core feature instead of a parallel
implementation.

Supported providers (framework-defined): cloudflared, tailscale, microsoft, serveo.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger("remote_link")

# Framework-defined providers (mirrors helpers/tunnel_manager.py).
SUPPORTED_PROVIDERS = ("cloudflared", "tailscale", "microsoft", "serveo")


# ── config ───────────────────────────────────────────────────────────────

def get_config() -> dict[str, Any]:
    """Read plugin config values (auto_start, provider)."""
    defaults = {
        "auto_start": False,
        "provider": "tailscale",
    }
    try:
        from helpers import plugins as _plugins
        cfg = _plugins.get_plugin_config("remote_link") or {}
        if isinstance(cfg, dict):
            defaults.update({k: v for k, v in cfg.items() if k in defaults})
    except Exception:
        pass
    return defaults


# ── tunnel server discovery ──────────────────────────────────────────────

def _server_base() -> str:
    """Resolve the tunnel API server base URL (mirrors api/tunnel_proxy.py)."""
    port = 55520
    try:
        from helpers import dotenv, runtime
        port = (
            runtime.get_arg("tunnel_api_port")
            or int(dotenv.get_dotenv_value("TUNNEL_API_PORT", 0))
            or 55520
        )
    except Exception:
        pass
    return f"http://localhost:{port}/"


def _post(action: str, payload: dict | None = None, timeout: int = 120) -> dict[str, Any]:
    """POST an action to the tunnel server. Returns parsed JSON or error dict."""
    body = {"action": action}
    if payload:
        body.update(payload)
    try:
        resp = requests.post(_server_base(), json=body, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        return {"success": False, "error": f"tunnel server HTTP {resp.status_code}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def health(timeout: int = 5) -> bool:
    """True if the tunnel API server is reachable."""
    try:
        resp = requests.post(_server_base(), json={"action": "health"}, timeout=timeout)
        return resp.status_code == 200 and bool(resp.json().get("success"))
    except Exception:
        return False


def wait_for_server(max_wait: float = 90.0, interval: float = 2.0) -> bool:
    """Poll health until the tunnel server is up or max_wait elapses."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if health():
            return True
        time.sleep(interval)
    return health()


# ── public API (mirrors the built-in actions) ────────────────────────────

def status() -> dict[str, Any]:
    """Return current remote-control tunnel state from the real system."""
    data = _post("get", timeout=10)
    return {
        "running": bool(data.get("is_running")),
        "url": data.get("tunnel_url") or "",
        "error": data.get("error", ""),
    }


def start(provider: str | None = None) -> dict[str, Any]:
    """Start the remote-control tunnel via the built-in system.

    If a tunnel is already running, returns its existing URL without creating a
    new one (so the URL is never regenerated on a restart).
    """
    cfg = get_config()
    provider = (provider or cfg.get("provider") or "tailscale").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        return {"running": False, "url": "", "error": f"Unsupported provider: {provider}"}

    # Never regenerate a running tunnel.
    cur = status()
    if cur["running"] and cur["url"]:
        return {"running": True, "url": cur["url"], "provider": provider, "reused": True}

    data = _post("create", {"provider": provider}, timeout=180)
    if data.get("success") and data.get("tunnel_url"):
        return {
            "running": True,
            "url": data["tunnel_url"],
            "provider": provider,
            "reused": False,
        }
    return {
        "running": False,
        "url": "",
        "provider": provider,
        "error": data.get("message") or data.get("error") or "Failed to start tunnel",
    }


def stop() -> dict[str, Any]:
    """Stop the running remote-control tunnel via the built-in system."""
    data = _post("stop", timeout=30)
    return {
        "running": False,
        "url": "",
        "error": "" if data.get("success") else (data.get("error") or "Failed to stop tunnel"),
    }
