from __future__ import annotations

from typing import Any

from helpers.extension import Extension
from usr.plugins.browser_session_sync.helpers.session_sync import auto_restore_core_session


class BrowserSessionRestoreOnRuntimeStart(Extension):
    """Restore before the native runtime exposes its first tab listing."""

    async def execute(
        self,
        runtime: Any = None,
        context_id: str = "",
        **kwargs: Any,
    ) -> None:
        if runtime is None:
            return
        try:
            message = await auto_restore_core_session(runtime)
            print(f"[browser_session_sync] runtime startup: {message}")
        except Exception as exc:
            print(f"[browser_session_sync] runtime startup restore skipped: {exc}")
