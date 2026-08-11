# AI-Link Bridge Plugin (Draft Scaffold)

This is the portable backend bridge package for the AI-Link client prototype.

## Purpose

- Provide a plugin-first backend surface for AI-Link Unity client sessions.
- Expose health, capabilities, session state, and metrics endpoints.
- Provide task-trigger scaffolding for a Manifold Pipe style AgentSpine/AINexus interaction path; it validates requests but does not dispatch agent work.
- Remain transferable for later AINexus seeding (AI-54) and plugin registry standardization (AI-56).

## Initial contract

- Protocol version: `ailink.v1`
- Transport targets: HTTP + WebSocket bridge scaffolding
- Client message types:
  - `hello`
  - `stream.start`
  - `stream.stop`
  - `video.frame`
  - `audio.frame`
  - `stats`
  - `ping`
  - `task.request`
- Server message types:
  - `hello.ack`
  - `capabilities`
  - `session.state`
  - `task.status`
  - `task.result`
  - `pong`
  - `error`

`taskBridge` is intentionally reported as `false` in capabilities while
`taskScaffold` is `true`. A `POST /task` response of `202 scaffolded` means the
payload was accepted as a draft contract check only, not that an Agent Zero or
Agent Spine task started.

## Files

- `plugin.yaml` - plugin manifest draft
- `default_config.yaml` - settings defaults
- `helpers/protocol.py` - protocol constants and validators
- `helpers/session_state.py` - in-memory session tracking
- `tools/ai_link_bridge_status.py` - status surface prototype
- `tools/ai_link_bridge_task.py` - task trigger surface prototype
- `docs/protocol.md` - protocol specification
- `tests/smoke_check.py` - local scaffold checks

## Transfer intent

This plugin scaffold is designed to move into an AgentSpine/A0 plugin directory or an AINexus seed repo later with minimal changes.
