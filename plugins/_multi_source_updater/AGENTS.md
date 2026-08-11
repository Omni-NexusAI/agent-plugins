# Multi Source Updater DOX

## Purpose

`_multi_source_updater` is the built-in Agentspine home for update source
selection and source-aware updater behavior.

## Ownership

- `plugin.yaml` owns package identity, version, and backup/update
  settings-section association.
- `helpers/source.py` owns source persistence, discovery, self-update runtime
  adaptation, and bootstrap-manager compatibility gating.
- `extensions/python/startup_migration/_10_multi_source_updater.py` applies the
  updater adapter before self-update API routes; agent-init repeats it
  idempotently for later lifecycle paths.
- `api/source.py` owns the browser-safe source persistence endpoint.
- `webui/config.html` owns the plugin Settings source selector and saves
  through the plugin API before the host’s generic modal closes.
- `extensions/webui/page-head/_10_multi_source_updater.html` owns the
  idempotent Advanced self-update source selector.

## Local Contracts

- Keep behavior limited to updater source selection, source-specific remotes,
  tag listing, dry-run payloads, and version display.
- Preserve upstream `agent0ai` update compatibility when that source is
  selected.
- Keep Agentspine/Omni-NexusAI remote selection explicit in status or dry-run
  output.
- Do not silently change the default update source.
- Do not modify `/exe`, the self-update manager, or other host-core files. A
  source that the bootstrap manager cannot honor must be blocked with a clear
  UI/API explanation instead of queued for restart.

## Work Guidance

- Keep saved source values limited to the named `UPDATE_SOURCES` entries.
- Preserve unrelated plugin config keys on save.
- Keep Agent Spine tag handling compatible with `standard`/`cuda` stable and
  pre-release variants without pretending that the upstream bootstrap manager
  can execute them.

## Verification

- Parse touched Python files.
- Select each updater source, save, and confirm the choice persists.
- Confirm the selected remote URL and bootstrap execution state are visible.

## Child DOX Index

This plugin has no child DOX files.
