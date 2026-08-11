"""
AI-Link Bridge Server

Standalone async bridge server that handles:
- HTTP endpoints: health, capabilities, sessions, metrics, task trigger
- WebSocket connections: stream/control channel for Unity client

Runs alongside AgentSpine/A0 as a companion service.
Can also run standalone for development/testing.
"""

import asyncio
import json
import time
import logging
import os
from typing import Optional

# Third-party imports (available in A0 venv)
try:
    from aiohttp import web, WSMsgType
except ImportError:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    web = None

try:
    from usr.plugins.ai_link_bridge.helpers.protocol import (
        PROTOCOL_VERSION,
        CLIENT_MESSAGE_TYPES,
        SERVER_MESSAGE_TYPES,
        BridgeMessage,
        capabilities_payload,
    )
    from usr.plugins.ai_link_bridge.helpers.session_state import (
        SESSIONS,
        get_or_create_session,
        summarize_sessions,
        BridgeSession,
    )
except ModuleNotFoundError:  # standalone plugin-root execution
    from helpers.protocol import (
        PROTOCOL_VERSION,
        CLIENT_MESSAGE_TYPES,
        SERVER_MESSAGE_TYPES,
        BridgeMessage,
        capabilities_payload,
    )
    from helpers.session_state import (
        SESSIONS,
        get_or_create_session,
        summarize_sessions,
        BridgeSession,
    )

logger = logging.getLogger("ai_link_bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


class BridgeConfig:
    """Load configuration from default_config.yaml or environment."""

    def __init__(self):
        self.protocol_version = PROTOCOL_VERSION
        self.host = os.environ.get("AI_LINK_HOST", "0.0.0.0")
        self.port = int(os.environ.get("AI_LINK_PORT", "8765"))
        self.enable_ws = os.environ.get("AI_LINK_ENABLE_WS", "true").lower() == "true"
        self.enable_http = os.environ.get("AI_LINK_ENABLE_HTTP", "true").lower() == "true"
        self.auth_token = os.environ.get("AI_LINK_AUTH_TOKEN", "")
        self.max_sessions = int(os.environ.get("AI_LINK_MAX_SESSIONS", "4"))
        self.require_auth = bool(self.auth_token)


def _json_response(data: dict, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, indent=2),
        status=status,
        content_type="application/json",
    )


def _check_auth(request: web.Request, config: BridgeConfig) -> Optional[web.Response]:
    if not config.require_auth:
        return None
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != config.auth_token:
        return _json_response({"error": "unauthorized"}, 401)
    return None


# --- HTTP Handlers ---

async def handle_health(request: web.Request) -> web.Response:
    """GET /health"""
    return _json_response({
        "status": "ok",
        "protocol": PROTOCOL_VERSION,
        "uptime_seconds": time.time() - request.app["start_time"],
        "active_sessions": len([s for s in SESSIONS.values() if s.connected]),
    })


async def handle_capabilities(request: web.Request) -> web.Response:
    """GET /capabilities"""
    config: BridgeConfig = request.app["config"]
    auth_err = _check_auth(request, config)
    if auth_err:
        return auth_err
    return _json_response({
        "protocol": PROTOCOL_VERSION,
        "capabilities": capabilities_payload(),
        "endpoints": {
            "health": "/health",
            "capabilities": "/capabilities",
            "sessions": "/sessions",
            "metrics": "/metrics",
            "task": "/task",
            "websocket": "/ws",
        },
    })


async def handle_sessions(request: web.Request) -> web.Response:
    """GET /sessions"""
    config: BridgeConfig = request.app["config"]
    auth_err = _check_auth(request, config)
    if auth_err:
        return auth_err
    return _json_response({"sessions": summarize_sessions()})


async def handle_metrics(request: web.Request) -> web.Response:
    """GET /metrics"""
    config: BridgeConfig = request.app["config"]
    auth_err = _check_auth(request, config)
    if auth_err:
        return auth_err
    sessions = summarize_sessions()
    total_video_frames = sum(s.get("metrics", {}).get("videoFrames", 0) for s in sessions)
    total_audio_frames = sum(s.get("metrics", {}).get("audioFrames", 0) for s in sessions)
    total_dropped = sum(s.get("metrics", {}).get("droppedFrames", 0) for s in sessions)
    return _json_response({
        "total_sessions": len(sessions),
        "active_sessions": len([s for s in sessions if s.get("connected")]),
        "total_video_frames": total_video_frames,
        "total_audio_frames": total_audio_frames,
        "total_dropped_frames": total_dropped,
        "sessions": sessions,
    })


async def handle_task(request: web.Request) -> web.Response:
    """POST /task â€” Manifold Pipe-style task trigger"""
    config: BridgeConfig = request.app["config"]
    auth_err = _check_auth(request, config)
    if auth_err:
        return auth_err

    try:
        body = await request.json()
    except Exception:
        return _json_response({"error": "invalid JSON body"}, 400)

    session_id = body.get("session_id", "")
    prompt = body.get("prompt", "")
    route = body.get("route", "default")

    if not prompt:
        return _json_response({"error": "prompt is required"}, 400)

    # This draft only validates and records a task scaffold; it does not
    # dispatch work to Agent Zero or Agent Spine.
    task_id = f"task-{int(time.time() * 1000)}"
    logger.info(f"Task accepted: {task_id} session={session_id} route={route} prompt_len={len(prompt)}")

    return _json_response({
        "status": "scaffolded",
        "task_id": task_id,
        "session_id": session_id,
        "route": route,
        "message": "Task scaffold accepted; no Agent Spine task was dispatched.",
        "protocol": PROTOCOL_VERSION,
    }, 202)


# --- WebSocket Handler ---

async def handle_websocket(request: web.Request) -> web.Response:
    """WS /ws â€” Main client stream/control channel"""
    config: BridgeConfig = request.app["config"]

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    session_id = None
    session: Optional[BridgeSession] = None
    logger.info("WebSocket client connected")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # Control message (JSON envelope)
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("messageType", "")

                    if msg_type == "hello":
                        # Client handshake
                        session_id = data.get("sessionId", "unknown")
                        payload = data.get("payload", {})
                        session = get_or_create_session(
                            session_id,
                            client_name=payload.get("clientName", "unknown"),
                        )
                        logger.info(f"Hello from client: {session_id} ({payload.get('clientName')})")

                        # Send hello.ack
                        ack = BridgeMessage(
                            protocolVersion=PROTOCOL_VERSION,
                            messageType="hello.ack",
                            sessionId=session_id,
                            timestampMs=int(time.time() * 1000),
                            payloadFormat="json",
                            payload={
                                "status": "connected",
                                "protocol": PROTOCOL_VERSION,
                                "capabilities": capabilities_payload(),
                            },
                        )
                        await ws.send_str(ack.to_json())

                    elif msg_type == "stream.start":
                        if session:
                            payload = data.get("payload", {})
                            session.capture_source = payload.get("captureMode", "Unknown")
                            session.video_format = payload.get("codec", "Unknown")
                            logger.info(f"Stream started: {session_id} mode={session.capture_source}")

                            ack = BridgeMessage(
                                protocolVersion=PROTOCOL_VERSION,
                                messageType="stream.start.ack",
                                sessionId=session_id,
                                timestampMs=int(time.time() * 1000),
                                payloadFormat="json",
                                payload={"status": "streaming"},
                            )
                            await ws.send_str(ack.to_json())

                    elif msg_type == "stream.stop":
                        if session:
                            session.connected = False
                            logger.info(f"Stream stopped: {session_id}")

                            ack = BridgeMessage(
                                protocolVersion=PROTOCOL_VERSION,
                                messageType="stream.stop.ack",
                                sessionId=session_id,
                                timestampMs=int(time.time() * 1000),
                                payloadFormat="json",
                                payload={"status": "stopped"},
                            )
                            await ws.send_str(ack.to_json())

                    elif msg_type == "stats":
                        if session:
                            payload = data.get("payload", {})
                            session.metrics.video_frames = payload.get("videoFramesSent", 0)
                            session.metrics.audio_frames = payload.get("audioFramesSent", 0)
                            session.metrics.dropped_frames = payload.get("droppedFrames", 0)
                            session.metrics.reconnect_count = payload.get("reconnectCount", 0)
                            latency = payload.get("networkLatencyMs", 0.0)
                            if latency > 0:
                                session.metrics.last_latency_ms = latency
                            session.last_seen_at = time.time() * 1000

                    elif msg_type == "ping":
                        pong = BridgeMessage(
                            protocolVersion=PROTOCOL_VERSION,
                            messageType="pong",
                            sessionId=session_id or "",
                            timestampMs=int(time.time() * 1000),
                            payloadFormat="json",
                            payload={"serverTimeMs": int(time.time() * 1000)},
                        )
                        await ws.send_str(pong.to_json())

                    else:
                        logger.warning(f"Unknown message type: {msg_type}")

                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON text message")

            elif msg.type == WSMsgType.BINARY:
                # Binary media payload: [1-byte type][8-byte timestamp][payload]
                if len(msg.data) < 9:
                    continue

                media_type = msg.data[0]
                # 0 = Opus audio, 1 = JPEG video
                if session:
                    if media_type == 1:
                        session.metrics.video_frames += 1
                    elif media_type == 0:
                        session.metrics.audio_frames += 1
                    session.last_seen_at = time.time() * 1000

                # Echo stats back periodically (every 30 frames)
                if session and session.metrics.video_frames % 30 == 0:
                    stats = BridgeMessage(
                        protocolVersion=PROTOCOL_VERSION,
                        messageType="stats",
                        sessionId=session_id or "",
                        timestampMs=int(time.time() * 1000),
                        payloadFormat="json",
                        payload={
                            "serverVideoFramesReceived": session.metrics.video_frames,
                            "serverAudioFramesReceived": session.metrics.audio_frames,
                            "serverDroppedFrames": session.metrics.dropped_frames,
                        },
                    )
                    await ws.send_str(stats.to_json())

            elif msg.type == WSMsgType.ERROR:
                logger.error(f"WebSocket error: {ws.exception()}")
                break

    except Exception as e:
        logger.error(f"WebSocket handler error: {e}")
    finally:
        if session:
            session.connected = False
        logger.info(f"WebSocket client disconnected: {session_id}")

    return ws


# --- App Factory ---

def create_app(config: Optional[BridgeConfig] = None) -> web.Application:
    config = config or BridgeConfig()

    app = web.Application()
    app["config"] = config
    app["start_time"] = time.time()

    # HTTP routes
    app.router.add_get("/health", handle_health)
    app.router.add_get("/capabilities", handle_capabilities)
    app.router.add_get("/sessions", handle_sessions)
    app.router.add_get("/metrics", handle_metrics)
    app.router.add_post("/task", handle_task)

    # WebSocket route
    if config.enable_ws:
        app.router.add_get("/ws", handle_websocket)

    logger.info(f"AI-Link Bridge initialized: host={config.host} port={config.port} ws={config.enable_ws}")
    return app


def main():
    config = BridgeConfig()
    app = create_app(config)
    logger.info(f"Starting AI-Link Bridge Server on {config.host}:{config.port}")
    web.run_app(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
