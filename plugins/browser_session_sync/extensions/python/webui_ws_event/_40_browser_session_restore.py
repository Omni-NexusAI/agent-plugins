from __future__ import annotations

from typing import Any

from helpers.extension import Extension
from usr.plugins.browser_session_sync.helpers.session_sync import (
    auto_restore_runtime_session_for_context,
)


class BrowserSessionViewerFallback(Extension):
    """Early compatibility bootstrap for hosts without browser_runtime_started.

    The _40 prefix deliberately runs before the native _browser WebSocket
    extension. On current hosts the runtime-start hook consumes the restore
    attempt first, making this a no-op.
    """

    async def execute(
        self,
        event_type: str = "",
        data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if event_type != "browser_viewer_subscribe" or not data:
            return
        context_id = str(data.get("context_id") or data.get("contextId") or "").strip()
        if not context_id:
            return
        try:
            message = await auto_restore_runtime_session_for_context(context_id)
            print(f"[browser_session_sync] viewer startup fallback: {message}")
        except Exception as exc:
            print(f"[browser_session_sync] viewer startup fallback failed for {context_id}: {exc}")
