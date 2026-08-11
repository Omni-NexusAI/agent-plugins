# Agentspine Identity Module

Agentspine built-in identity and branding overlay.

## Purpose

`_agentspine_identity` keeps Agentspine product identity in a plugin package so
the core application can stay close to upstream A0. It applies the Agentspine
name, release banner, initial greeting, and visible UI copy at runtime.

This is an underscore built-in overlay. It is always enabled in Agentspine
builds and is not intended for marketplace distribution.

Its runtime gate is explicit: the Spine 9.9 release overlays set
`AGENTSPINE_RELEASE=9.9` and `AGENTSPINE_IDENTITY_ENABLED=true`. The plugin
therefore remains inert in A0/v2.7 custom-plugin deployments even if its source
is present elsewhere.

## Runtime Design

- `plugin.yaml` marks the plugin as `always_enabled`.
- `default_config.yaml` defines product names, banner prefixes, compatibility
  labels, and release-tag defaults.
- `helpers/identity.py` loads simple YAML defaults, normalizes release tags,
  formats display versions, and applies protected text replacements.
- `extensions/python/agent_init/_10_initial_message.py` rewrites the initial
  main-agent greeting before it is inserted into chat history.
- `extensions/python/banners/_95_agentspine_identity.py` rewrites banner
  strings emitted by backend banner extensions.
- `extensions/python/_functions/helpers/ui_server/UiRouteHandlers/serve_index/end/_10_agentspine_index_identity.py`
  patches the served HTML title and `globalThis.gitinfo` version payload.
- `extensions/webui/page-head/_10_agentspine_identity.html` patches browser
  title, visible text, selected attributes, sidebar version label, and dynamic
  UI mutations.

## How It Functions

The backend helper protects phrases that must not be rewritten, applies a fixed
replacement table, then restores protected phrases. The 9.9 release targets
use `M v0.9.9-standard` and `M v0.9.9-gpu`; `D` remains reserved for explicitly
named pre/development tags. The index hook reads the explicit Compose
`BUILD_VARIANT` (`standard` or `cuda`) so the browser reflects the target that
is actually running.

The frontend patch mirrors the replacement table for text created after page
load. It sets `document.title`, updates `globalThis.agentspineIdentity`,
exposes `globalThis.a0VersionBanner`, patches the Alpine `sidebarBottom`
`versionLabel` getter, rewrites common UI roots, and watches DOM mutations for
late-rendered Agent Zero text.

## Configuration Surface

`default_config.yaml` currently controls:

- `product_name`
- `short_name`
- `banner_prefix`
- `main_release_prefix`
- `development_prefix`
- `compatibility_label`
- `default_release_tag`
- `release_tags.standard`
- `release_tags.gpu`
- `release_tags.standard_pre`
- `release_tags.gpu_pre`

## Safe Extension Points

- Add new identity strings in `helpers/identity.py` and mirror them in the
  frontend patch when browser-rendered text needs the same behavior.
- Add new release-tag variants in `default_config.yaml` and `_current_release_tag`.
- Add narrowly scoped UI roots or attributes to the page-head patch when new UI
  surfaces appear.

## Compatibility Notes

- Keep protected phrases for cases where "Agent Zero" is part of a proper name.
- Avoid rewriting inside script, style, code, pre, textarea, and input elements.
- Preserve `D` for development/pre builds and `M` for main/full release builds
  unless release policy changes.
- Keep the backend and frontend replacement tables synchronized.

## Verification Checklist

- Compile the plugin Python files.
- Load the app and confirm the browser title is `Agentspine`.
- Confirm standard renders `M v0.9.9-standard` and CUDA renders
  `M v0.9.9-gpu`, each with timestamp when available.
- Start a fresh main-agent chat and confirm the initial greeting is branded.
- Open settings/modals/toasts and confirm late-rendered visible copy is
  rewritten without modifying protected phrases.
