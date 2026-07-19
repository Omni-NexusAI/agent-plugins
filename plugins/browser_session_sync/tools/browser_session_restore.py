from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers.tool import Response, Tool
from usr.plugins.browser_session_sync.helpers.session_sync import (
    SAVE_DIR,
    MANIFEST_FILE_NAME,
    restore_runtime_session_for_context,
)


class BrowserSessionRestore(Tool):
    async def execute(self, **kwargs: Any) -> Response:
        context_id = str(kwargs.get("context_id") or self.agent.context.id)
        filename = kwargs.get("filename") or None
        list_only = kwargs.get("list", False)

        if list_only:
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            files_list = sorted(
                [path for path in SAVE_DIR.glob("*.json") if path.name != MANIFEST_FILE_NAME],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not files_list:
                return Response(text="No saved browser sessions found.")
            result = "**Saved browser sessions:**\n\n"
            for path in files_list:
                result += f"- `{path.name}` ({path.stat().st_size:,} bytes)\n"
            return Response(text=result)

        if filename:
            requested = Path(str(filename))
            if requested.name != filename:
                return Response(text=f"Invalid session filename: {filename}")

        try:
            message = await restore_runtime_session_for_context(context_id, filename, force=True)
        except Exception as exc:
            message = f"Failed to restore session: {exc}"
        return Response(text=message)
