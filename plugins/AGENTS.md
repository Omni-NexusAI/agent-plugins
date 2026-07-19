# Plugins DOX

## Purpose

`plugins/` contains Agent Zero-compatible plugin packages. Each child plugin folder should be understandable and maintainable on its own.

## Ownership

- `plugin.yaml` owns plugin identity, version, title, description, enablement, and settings-section placement.
- `README.md` owns user-facing purpose, compatibility, behavior, and configuration notes.
- `default_config.yaml` owns plugin defaults where present.
- `extensions/` owns runtime hooks loaded by the Agent Zero plugin framework.
- `helpers/`, `api/`, and `webui/` own plugin-local backend, route, UI, and asset code where present.

## Local Contracts

- Read this file and the target plugin's `AGENTS.md` before editing a plugin.
- Keep each plugin self-contained enough to sync into an individual repository.
- Keep runtime patches idempotent and safe on unsupported hosts.
- Do not rename underscore-prefixed Agentspine plugin folders unless imports, manifests, docs, and deployment paths are updated together.
- Document compatibility gaps instead of silently relying on one local runtime.

## Work Guidance

- Put host-store or DOM patches in WebUI extension files with clear guards.
- Put reusable backend behavior in helpers rather than embedding it in route handlers.
- Prefer explicit defaults and migration helpers over implicit UI-only defaults.
- Keep UI classes, text styling, and label formats documented when other agents need to reproduce a design.
- If a plugin is container-synced, preserve its source behavior until a deliberate upgrade is requested.

## Verification

- Confirm plugin files can be copied independently.
- Verify unsupported hosts do not throw unhandled errors during startup or page load.
- Check that README, DOX, manifests, and default config agree after changes.
- For container syncs, remove `__pycache__` and `.pyc` files before committing.

## Child DOX Index

- `browser_session_sync/AGENTS.md`: plugin-owned browser session restore, current-state tracking, manual recovery, and performance safeguards.
- `_agentspine_identity/AGENTS.md`: Agentspine product identity overlay, greeting, banner, title, and version display.
- `_enhanced_mcp_config/AGENTS.md`: MCP settings UI, disabled flag handling, status/apply/toggle API handlers, and override payload copied from the GPU-pre container.
- `_enhanced_speech/AGENTS.md`: remote Kokoro TTS support, speech settings UI, detection/defaults, and enhanced STT recorder patch.
- `_multi_source_updater/AGENTS.md`: source-aware self-update helper/settings/UI override payload copied from the GPU-pre container.
- `provider_profiles/AGENTS.md`: portable provider-aware model, API base, and context-length restore behavior mirroring the GPU-pre container's `_model_config`.
