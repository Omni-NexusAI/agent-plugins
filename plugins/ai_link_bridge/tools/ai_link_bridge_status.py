from __future__ import annotations

try:
    from usr.plugins.ai_link_bridge.helpers.protocol import PROTOCOL_VERSION, capabilities_payload
    from usr.plugins.ai_link_bridge.helpers.session_state import summarize_sessions
except ModuleNotFoundError:  # source-tree smoke checks
    from plugins.ai_link_bridge.helpers.protocol import PROTOCOL_VERSION, capabilities_payload
    from plugins.ai_link_bridge.helpers.session_state import summarize_sessions


class AI_Link_Bridge_Status:
    async def execute(self, **kwargs):
        return {
            "ok": True,
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": capabilities_payload(),
            "sessions": summarize_sessions(),
        }
