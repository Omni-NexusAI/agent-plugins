# AI Link Bridge

## Purpose

Portable early-stage bridge scaffolding for AI Link sessions. It is included in
Agent Spine 9.9 unchanged as a compatibility target and future AINexus seed.

## Local Contracts

- Keep the plugin truthful about scaffolded versus implemented capabilities.
- Report `taskBridge: false` and `taskScaffold: true` until an actual Agent Zero/Agent Spine dispatcher exists; a `202 scaffolded` task response is not execution.
- Preserve the `ailink.v1` protocol surface unless a deliberate protocol change
  updates the documentation and smoke checks together.
- `webui/thumbnail.svg` owns the plugin-card icon.
- Keep the plugin local; it must not patch Agent Zero core files.

## Verification

- Run its smoke checks and parse its Python files.
