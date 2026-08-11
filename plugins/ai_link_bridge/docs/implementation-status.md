# AI-Link Bridge Implementation Status

**Last updated**: 2026-07-30
**Sprint scope**: AI-32, AI-33, AI-35 (combined prototype-validation pass)

## Verification Results

| Check | Result |
|---|---|
| Backend module imports | âœ… Passed |
| Protocol version | ailink.v1 |
| Session creation | âœ… Passed |
| Bridge app creation | âœ… 11 routes registered |
| aiohttp dependency | âœ… v3.13.5 installed |

## Backend Bridge Server

**File**: `bridge_server.py` (340 lines)
**Startup**: `./start_bridge.sh [port] [host]`
**Default**: `0.0.0.0:8765`

### HTTP Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /health | Server health + uptime |
| GET | /capabilities | Protocol capabilities |
| GET | /sessions | Active client sessions |
| GET | /metrics | Aggregate session metrics |
| POST | /task | Manifold Pipe task trigger |

### WebSocket Channel

| Path | Purpose |
|---|---|
| WS /ws | Client stream/control channel |

### Supported Bridge Messages

| Client â†’ Server | Server â†’ Client |
|---|---|
| hello | hello.ack |
| stream.start | stream.start.ack |
| stream.stop | stream.stop.ack |
| stats | stats |
| ping | pong |
| auth | â€” |
| Binary (type 0: audio, type 1: video) | Periodic stats echo |

## Unity Client Changes

### New Scripts

| File | Lines | Purpose |
|---|---|---|
| AILinkProtocol.cs | ~60 | Protocol constants and version |
| AILinkCaptureSource.cs | ~50 | Capture source interface |
| PassthroughCameraCaptureSource.cs | ~90 | Meta MRUK passthrough capture |
| DesktopCameraCaptureSource.cs | ~70 | Desktop camera fallback |
| FrameEncodingUtils.cs | ~60 | Texture-to-JPEG helper |

### Refactored Scripts

| File | Lines | Changes |
|---|---|---|
| AILinkClient.cs | 440 | Bridge session/protocol events, hello/lifecycle/stats, reconnect tracking |
| WebSocketClient.cs | 768 | BridgeEnvelope parser, protocol messages, bridge events, legacy compat |
| VideoManager.cs | Refactored | Source-agnostic capture, passthrough-first selection |
| ConfigManager.cs | Updated | Bridge config model + captureMode |
| AppConfig.json | Updated | Bridge settings defaults |

### Unchanged (Compatible)

| File | Status |
|---|---|
| AudioManager.cs | âœ… Binary path (Opus type 0) unchanged, fully compatible |
| LatencyMonitor.cs | âœ… Compatible with existing latency channels |
| LatencyHUD.cs | âœ… Compatible with existing display |

## Configuration

### Bridge Config (AppConfig.json)

```json
{
  "bridge": {
    "protocolVersion": "ailink.v1",
    "sessionId": "",
    "statsIntervalSeconds": 1.0
  },
  "video": {
    "captureMode": "Auto",
    "captureFps": 30,
    "captureWidth": 1280,
    "captureHeight": 720,
    "jpegQuality": 80
  }
}
```

### Environment Variables (bridge_server.py)

| Variable | Default | Purpose |
|---|---|---|
| AI_LINK_HOST | 0.0.0.0 | Bind address |
| AI_LINK_PORT | 8765 | Bind port |
| AI_LINK_AUTH_TOKEN | (empty) | Auth token (optional) |
| AI_LINK_ENABLE_WS | true | Enable WebSocket channel |
| AI_LINK_ENABLE_HTTP | true | Enable HTTP endpoints |
| AI_LINK_MAX_SESSIONS | 4 | Max concurrent sessions |

## Testing Instructions

### 1. Start the bridge server

```bash
cd /a0/usr/plugins/ai_link_bridge
chmod +x start_bridge.sh
./start_bridge.sh
```

### 2. Test HTTP endpoints

```bash
curl http://localhost:8765/health
curl http://localhost:8765/capabilities
curl http://localhost:8765/sessions
curl -X POST http://localhost:8765/task -H 'Content-Type: application/json' -d '{"prompt":"test task","session_id":"manual-test"}'
```

### 3. Connect from Unity client

- Ensure `AppConfig.json` serverUrl points to the bridge server
- Open the AI-Link Unity project
- Enter play mode (or build for Quest)
- Check console logs for: hello sent â†’ hello.ack received â†’ stream lifecycle

### 4. Verify binary media transport

- Start streaming from client
- Watch bridge server logs for binary frame reception
- Check /sessions and /metrics endpoints for live stats

## Known Gaps (for AI-35 hardening)

- [ ] Unity compile/runtime verification
- [ ] Meta MRUK API exact symbol verification
- [ ] Frame-drop detection and reporting
- [ ] 20-minute soak test procedure
- [ ] Reconnect resume with sequence gaps
- [ ] Latency HUD expansion for bridge metrics
# Implementation status

The `ailink.v1` HTTP, WebSocket, capability, and in-memory session surfaces are
implemented as a plugin-local draft. Task requests are scaffolded only: no
Agent Zero, Agent Spine, or AINexus task dispatch is implemented yet.
