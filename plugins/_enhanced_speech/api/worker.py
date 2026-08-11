from __future__ import annotations

from helpers.api import ApiHandler, Request, Response

try:
    from plugins._enhanced_speech.helpers import remote_worker
except Exception:
    from usr.plugins._enhanced_speech.helpers import remote_worker


class Worker(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        timeout = input.get("remote_timeout", input.get("timeout", 3))
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError):
            timeout_value = 3.0
        return remote_worker.check_worker(
            remote_url=str(input.get("remote_url", "") or ""),
            remote_token=str(input.get("remote_token", "") or ""),
            remote_timeout=timeout_value,
        )
