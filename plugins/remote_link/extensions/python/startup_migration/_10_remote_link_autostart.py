"""Auto-start Agent Zero's built-in Remote Control tunnel at framework boot.

This extension does NOT spawn its own tunnel. It waits for the tunnel API
server (run_tunnel.py) to come up, then drives the SAME remote-control system
the WebUI "Remote Control" panel uses. If a tunnel is already running it reuses
the existing URL instead of generating a new one.
"""

from __future__ import annotations

import logging
import threading

from helpers.extension import Extension
from usr.plugins.remote_link.helpers.tunnel_manager import (
    get_config,
    start,
    status,
    wait_for_server,
)

log = logging.getLogger("remote_link.autostart")


class RemoteLinkAutostart(Extension):
    def execute(self, **kwargs) -> None:
        cfg = get_config()
        if not cfg.get("auto_start", False):
            log.debug("Remote Link auto-start disabled; skipping.")
            return

        provider = str(cfg.get("provider", "tailscale"))
        log.info("Remote Link auto-start queued: provider=%s", provider)

        thread = threading.Thread(
            target=_autostart_worker,
            args=(provider,),
            daemon=True,
            name="remote-link-autostart",
        )
        thread.start()


def _autostart_worker(provider: str) -> None:
    """Background thread so framework startup is never blocked."""
    try:
        # The tunnel server is a separate process launched at container boot;
        # give it time to become reachable before driving it.
        if not wait_for_server(max_wait=90.0):
            log.warning(
                "Remote Link auto-start: tunnel server not reachable; "
                "Remote Control will start on demand from the UI."
            )
            return

        cur = status()
        if cur.get("running") and cur.get("url"):
            log.info(
                "Remote Link: Remote Control already active, reusing URL: %s",
                cur["url"],
            )
            return

        result = start(provider=provider)
        if result.get("running") and result.get("url"):
            log.info(
                "Remote Link auto-started Remote Control (%s): %s",
                provider,
                result["url"],
            )
        else:
            log.warning(
                "Remote Link auto-start failed: %s",
                result.get("error", "unknown error"),
            )
    except Exception as exc:
        log.warning("Remote Link auto-start error: %s", exc)
