"""API handler for Remote Link — drives Agent Zero's built-in Remote Control."""

from __future__ import annotations

import logging

from helpers.api import ApiHandler, Request, Response
from usr.plugins.remote_link.helpers.tunnel_manager import (
    SUPPORTED_PROVIDERS,
    get_config,
    start,
    status,
    stop,
)

log = logging.getLogger("remote_link.api")


class RemoteLinkApi(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        action = str(input.get("action", "status"))

        if action == "start":
            provider = input.get("provider")
            result = start(provider=provider)
            return {"status": "ok", **result}

        if action == "stop":
            result = stop()
            return {"status": "ok", **result}

        if action == "status":
            result = status()
            cfg = get_config()
            return {
                "status": "ok",
                **result,
                "config": {
                    "auto_start": cfg.get("auto_start", False),
                    "provider": cfg.get("provider", "tailscale"),
                },
                "providers": list(SUPPORTED_PROVIDERS),
            }

        return {"status": "error", "message": f"Unknown action: {action}"}
