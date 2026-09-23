"""Configuration and explicit backend connectivity check for the plugin page."""

import os

from helpers import plugins
from helpers.api import ApiHandler, Request, Response
from usr.plugins.system_1.helpers.runtime import client_for


class Status(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        section = input.get("section", "main")
        if section not in {"main", "utility", "embedding"}:
            return Response(status=400, response="Unknown model section")
        config = plugins.get_plugin_config("system_1") or {}
        section_config = config.get(section, {})
        policy = config.get("policy", {})
        if not section_config.get("enabled"):
            return {"ok": True, "status": "disabled"}
        env_name = section_config.get("token_env", "")
        if section_config.get("backend") == "jev" and not os.environ.get(env_name, ""):
            return {"ok": True, "status": "unavailable", "detail": "Credential is missing"}
        if input.get("check") is True:
            try:
                result = await client_for(section_config, policy).choose(
                    "Connectivity check only. No action should execute.",
                    {"ready": "The service is ready.", "unknown": "The service is not ready."})
                return {"ok": True, "status": "available", "backend": result.backend}
            except Exception as error:
                return {"ok": True, "status": "unavailable", "detail": type(error).__name__}
        return {"ok": True, "status": "configured"}
