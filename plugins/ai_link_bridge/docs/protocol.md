# AI-Link Bridge Protocol Draft

Protocol version: `ailink.v1`

## Goals

- One explicit client/backend contract for AI-32, AI-33, and AI-35.
- Portable across AgentSpine/A0 and later AINexus.
- Support capture source negotiation, stream telemetry, task triggers, and XR-aware metadata.

## Client hello

```json
{
  "protocolVersion": "ailink.v1",
  "messageType": "hello",
  "sessionId": "uuid-or-guid",
  "timestampMs": 0,
  "sequence": 0,
  "payloadFormat": "json",
  "payload": {
    "clientName": "AI-Link Unity",
    "captureSource": "meta_passthrough_camera_access",
    "videoFormat": "jpeg",
    "audioFormat": "opus"
  }
}
```

## Metadata to preserve with frames

- timestampMs
- sessionId
- sequence
- camera intrinsics
- camera pose
- current resolution
- camera side (left/right)
- optional dropped-frame counters

## Stability requirements

- reconnect with same sessionId when possible
- sequence gaps increment dropped-frame count
- periodic `stats` messages emit fps/latency/uptime/reconnects
- fallback capture source remains available for non-Quest testing
