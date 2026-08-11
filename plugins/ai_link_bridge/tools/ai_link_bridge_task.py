from __future__ import annotations


class AI_Link_Bridge_Task:
    async def execute(self, session_id: str = "", prompt: str = "", route: str = "agentspine", **kwargs):
        return {
            "ok": True,
            "accepted": bool(prompt),
            "sessionId": session_id,
            "route": route,
            "status": "scaffolded" if prompt else "rejected",
            "message": "Task scaffold created only; it was not dispatched to Agent Zero or Agent Spine.",
        }
