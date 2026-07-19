from __future__ import annotations

from helpers.extension import Extension


class SaveBrowserSession(Extension):
    def execute(self, data: dict = {}, **kwargs):
        from usr.plugins.browser_session_sync.helpers.session_sync import (
            context_id_from_extension_data,
            handle_context_reset_sync,
        )

        context_id = context_id_from_extension_data(data)
        if not context_id:
            return
        try:
            handle_context_reset_sync(context_id)
        except Exception:
            pass
        return None
