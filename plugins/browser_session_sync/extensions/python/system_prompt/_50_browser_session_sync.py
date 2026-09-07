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
            "On current hosts, native Browser persistence owns shared sign-in and chat-owned tabs. "
            "This plugin keeps historical cookies/localStorage and tab snapshots for recovery.\n\n"
            "**Key behaviors:**\n"
            "- All user and agent tabs are saved after page loads and closes.\n"
            "- Cached sign-in is applied automatically only to a proven-empty native profile; cached tabs only when native saved tab state is absent.\n"
            "- A tab belongs to the active chat's native Browser runtime; do not try to pass a context id to the `browser` tool.\n\n"
            "**Before opening a tab:** Call the `browser` tool with `action: \"list\"`. "
            "Use the returned `browser_id` to inspect or interact with an existing tab. "
            "Do not assume browser id 1 is the desired tab, and do not use action: \"open\" merely to discover existing tabs.\n\n"
            "**To save explicitly:** Use tool `browser_session_sync.save` to snapshot the current context's state immediately.\n\n"
            "**To restore explicitly:** Use `browser_session_restore` with `list: true` to choose a snapshot, then `filename` to recover it. "
            "Identify that filename and explain that its sign-in cookies/localStorage affect the shared browser profile. "
            "Only restore when the user requested recovery. Only tabs owned by this chat are reopened; old unowned tabs from unrelated snapshots are skipped.\n\n"
            "**To use the user's pre-existing tabs:** list first, select the relevant `browser_id`, then navigate or interact with that tab directly.\n"
        )
        system_prompt.append(section)
