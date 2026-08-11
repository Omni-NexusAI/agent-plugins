from __future__ import annotations

from dataclasses import dataclass, field
from time import time


@dataclass(slots=True)
class SessionMetrics:
    reconnect_count: int = 0
    dropped_frames: int = 0
    video_frames: int = 0
    audio_frames: int = 0
    last_latency_ms: float = 0.0
    average_latency_ms: float = 0.0


@dataclass(slots=True)
class BridgeSession:
    session_id: str
    client_name: str = "unity-client"
    connected: bool = False
    capture_source: str = "unknown"
    video_format: str = "unknown"
    audio_format: str = "unknown"
    started_at: float = field(default_factory=time)
    last_seen_at: float = field(default_factory=time)
    metrics: SessionMetrics = field(default_factory=SessionMetrics)

    @property
    def uptime_ms(self) -> int:
        return int((time() - self.started_at) * 1000)


SESSIONS: dict[str, BridgeSession] = {}


def get_or_create_session(session_id: str, **kwargs) -> BridgeSession:
    if session_id not in SESSIONS:
        SESSIONS[session_id] = BridgeSession(
            session_id=session_id,
            **{k: v for k, v in kwargs.items() if k in BridgeSession.__dataclass_fields__},
        )
    session = SESSIONS[session_id]
    session.last_seen_at = time()
    # Update mutable fields if provided
    if "client_name" in kwargs:
        session.client_name = kwargs["client_name"]
    if "connected" in kwargs:
        session.connected = kwargs["connected"]
    return session


def summarize_sessions() -> list[dict]:
    return [
        {
            "sessionId": s.session_id,
            "connected": s.connected,
            "captureSource": s.capture_source,
            "videoFormat": s.video_format,
            "audioFormat": s.audio_format,
            "uptimeMs": s.uptime_ms,
            "metrics": {
                "reconnectCount": s.metrics.reconnect_count,
                "droppedFrames": s.metrics.dropped_frames,
                "videoFrames": s.metrics.video_frames,
                "audioFrames": s.metrics.audio_frames,
                "lastLatencyMs": s.metrics.last_latency_ms,
                "averageLatencyMs": s.metrics.average_latency_ms,
            },
        }
        for s in SESSIONS.values()
    ]
