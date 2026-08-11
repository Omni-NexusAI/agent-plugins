# Agentspine Identity DOX

## Purpose

`_agentspine_identity` owns Agentspine product identity, release-banner display,
initial greeting branding, and visible UI text rewrites.

## Ownership

- `default_config.yaml` owns product names, banner prefixes, compatibility
  labels, and release-tag defaults.
- `helpers/identity.py` owns backend identity configuration, version formatting,
  and protected text replacement rules.
- `extensions/python/agent_init/_10_initial_message.py` owns the branded initial
  main-agent greeting.
- `extensions/python/banners/_95_agentspine_identity.py` owns backend banner
  text rewrites.
- `extensions/python/_functions/helpers/ui_server/UiRouteHandlers/serve_index/end/_10_agentspine_index_identity.py`
  owns served-index title and `globalThis.gitinfo` patching.
- `extensions/webui/page-head/_10_agentspine_identity.html` owns browser-side
  title, sidebar version label, and late-rendered UI text rewrites.

## Local Contracts

- Keep backend and frontend replacement tables aligned.
- Preserve protected phrases when "Agent Zero" is part of a proper name.
- Use development/pre banner prefix `D` only for `-pre`/development tags and
  main/full release prefix `M` for the non-pre 9.9 standard and CUDA tags.
- The plugin is enabled only when the Spine release image explicitly supplies
  both `AGENTSPINE_RELEASE=9.9` and `AGENTSPINE_IDENTITY_ENABLED=true`.
  Keep those gates out of A0/v2.7 custom-plugin deployments.
- Do not rewrite script, style, code, pre, textarea, or input content.

## Work Guidance

- Add release variants in both `default_config.yaml` and the helper/index-hook
  variant resolver. Compose must provide `BUILD_VARIANT=standard` or `cuda` so
  the browser label reflects the actual same-revision release target.
- Add identity text replacements in `helpers/identity.py` and mirror browser
  equivalents in the page-head hook.
- Keep DOM rewrite scopes narrow enough to avoid unnecessary page churn.

## Verification

- Parse touched Python files.
- Confirm the browser title, sidebar version label, and fresh-chat greeting are
  branded correctly.
- Confirm late-rendered modals/toasts are rewritten without touching protected
  phrases.

## Child DOX Index

This plugin has no child DOX files.
