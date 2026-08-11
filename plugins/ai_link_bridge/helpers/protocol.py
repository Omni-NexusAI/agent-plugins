from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any
import json

PROTOCOL_VERSION = "ailink.v1"

CLIENT_MESSAGE_TYPES = {
    "hello",
    "stream.start",
    "stream.stop",
    "video.frame",
    "audio.frame",
    "stats",
    "ping",
    "task.request",
}

SERVER_MESSAGE_TYPES = {
    "hello.ack",
    "capabilities",
    "session.state",
    "task.status",
    "task.result",
    "pong",
    "error",
}


@dataclass(slots=True)
class BridgeMessage:
    protocolVersion: str
    messageType: str
    sessionId: str
    timestampMs: int
    sequence: int = 0
    payloadFormat: str = "json"
    payload: dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        return (
            self.protocolVersion == PROTOCOL_VERSION
            and bool(self.sessionId)
            and bool(self.messageType)
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BridgeMessage":
        return cls(
            protocolVersion=str(data.get("protocolVersion", "")),
            messageType=str(data.get("messageType", "")),
            sessionId=str(data.get("sessionId", "")),
            timestampMs=int(data.get("timestampMs", 0) or 0),
            sequence=int(data.get("sequence", 0) or 0),
            payloadFormat=str(data.get("payloadFormat", "json")),
            payload=dict(data.get("payload", {}) or {}),
        )


def capabilities_payload() -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "videoFormats": ["jpeg", "h264"],
        "audioFormats": ["opus"],
        "captureSources": ["meta_passthrough_camera_access", "desktop_camera", "simulated"],
        "taskBridge": False,
        "taskScaffold": True,
        "metrics": ["fps", "latency_ms", "dropped_frames", "reconnect_count", "uptime_ms"],
    }
