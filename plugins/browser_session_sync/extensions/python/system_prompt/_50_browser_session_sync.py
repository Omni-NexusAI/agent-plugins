from __future__ import annotations

from typing import Any

from helpers.extension import Extension


class BrowserSessionSyncPrompt(Extension):
    """Tell the agent how to reuse restored native Browser tabs."""

    async def execute(
        self,
        system_prompt: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        if system_prompt is None:
            return
        section = (
            "## Browser Session Persistence (GLOBAL)\n\n"
            "Browser sessions (cookies + localStorage) are persisted GLOBALLY as the latest saved session. "
            "Each active chat restores that session into its own native Browser runtime.\n\n"
            "**Key behaviors:**\n"
            "- All user and agent tabs are saved after page loads and closes.\n"
            "- A saved session is restored before the Browser viewer and `browser` tool list tabs.\n"
            "- A tab belongs to the active chat's native Browser runtime; do not try to pass a context id to the `browser` tool.\n\n"
            "**Before opening a tab:** Call the `browser` tool with `action: \"list\"`. "
            "Use the returned `browser_id` to inspect or interact with an existing tab. "
            "Do not assume browser id 1 is the desired tab, and do not use `action: \"open\"` merely to discover existing tabs.\n\n"
            "**To save explicitly:** Use tool `browser_session_sync.save` to snapshot the current context's state immediately.\n\n"
            "**To restore explicitly:** Use tool `browser_session_sync.restore` with `--list` to see available sessions, or `--filename` to load a specific one.\n\n"
            "**To use the user's pre-existing tabs:** list first, select the relevant `browser_id`, then navigate or interact with that tab directly.\n"
        )
        system_prompt.append(section)
