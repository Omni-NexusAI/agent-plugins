from __future__ import annotations

from typing import Any

from helpers.tool import Response, Tool
from usr.plugins.browser_session_sync.helpers.session_sync import (
    save_runtime_snapshot_for_context,
)


class BrowserSessionSave(Tool):
    """Manually save the current native Browser session."""

    async def execute(self, **kwargs: Any) -> Response:
        context_id = str(kwargs.get("context_id") or self.agent.context.id)
        try:
            message = await save_runtime_snapshot_for_context(context_id)
        except Exception as exc:
            message = f"Save failed: {exc}"
        return Response(text=message)
