"""Store a System 1 credential without returning it to the browser."""

import os
import re

from helpers import dotenv
from helpers.api import ApiHandler, Request, Response


class Credential(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        name = input.get("name", "")
        if not isinstance(name, str) or not re.fullmatch(r"SYSTEM_1_[A-Z0-9_]{1,48}", name):
            return Response(status=400, response="Invalid System 1 credential name")
        if input.get("action", "status") == "status":
            return {"ok": True, "has_key": bool(os.environ.get(name))}
        if input.get("action") == "set":
            value = input.get("value")
            if not isinstance(value, str) or len(value) > 4096 or "\n" in value or "\r" in value:
                return Response(status=400, response="Invalid credential value")
            dotenv.save_dotenv_value(name, value)
            return {"ok": True, "has_key": bool(value)}
        return Response(status=400, response="Unknown credential action")
