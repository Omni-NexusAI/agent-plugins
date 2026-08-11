# Multi Source Updater

Agent Spine built-in self-update source overlay.

## Purpose

`_multi_source_updater` provides the Agent Spine-owned update source selector.
It ships in both standard and CUDA images and is never included in an Agent Zero
custom-plugin deployment. It adapts the runtime self-update discovery APIs and
the existing self-update UI without editing Agent Zero source files.

## Runtime Design

- `default_config.yaml` establishes the explicit, persisted default source.
- `helpers/source.py` owns source normalization, remote/tag discovery, runtime
  updater adaptation, and the truthfulness gate for bootstrap execution.
- `extensions/python/startup_migration/_10_multi_source_updater.py` applies the
  adapter before self-update API routes are used; the agent-init hook repeats
  that idempotently for later host lifecycle paths.
- `api/source.py` saves the selected source through the supported plugin config
  API while retaining unrelated config keys.
- `webui/config.html` exposes the same persisted source selector from the
  plugin’s Settings action.
- `extensions/webui/page-head/_10_multi_source_updater.html` injects one
  source selector into the host's existing Advanced self-update panel.
- `webui/thumbnail.svg` is present for plugin catalog consistency.

## Intended Behavior Contract

Behavior represented by this plugin should stay limited to update source
selection and source-aware version display:

- Allow selecting between the Omni-NexusAI Agent Spine source and the upstream
  agent0ai source.
- Persist the selected source in settings.
- Use the selected source when listing tags, dry-running updates, or resolving
  update remotes.
- List source-appropriate tags: Agent Spine `vX.Y.Z-standard|cuda[-pre]` tags
  for Omni-NexusAI, and upstream `vX.Y` tags for agent0ai.

## Bootstrap Execution Boundary

The A0 v2.7 self-update manager starts before plugins load and receives its
remote through `A0_SELF_UPDATE_REMOTE_URL`. This plugin never edits `/exe` or
host files to override that behavior. The selected source is always persisted
and immediately governs discovery, status, branch choices, and tag choices.
Scheduling is allowed only when the selected upstream remote matches the image
manager; Agent Spine package updates are explicitly blocked by this v2.7
manager because it accepts upstream `vX.Y` targets only. The UI reports this
limitation before it can queue a misleading restart request.

## Safe Extension Points

- Add backend updater-source helpers under `helpers/`.
- Add migration logic to the existing agent-init hook for old settings shapes.
- Add WebUI patches under `extensions/webui` if the update settings page needs
  source controls that cannot be supplied by core settings metadata.

## Compatibility Notes

- Do not change the default update source without an explicit release decision.
- Keep source-specific remote URLs explicit in status/dry-run payloads so agents
  can verify the selected source without external context.
- Preserve upstream update compatibility when the selected source is `agent0ai`.
- Keep the plugin underscore-prefixed because this is a built-in overlay.

## Verification Checklist

- Compile the plugin Python files.
- Confirm startup and agent-init load the source adapter without errors.
- In Advanced self-update settings, select each source and verify the choice
  persists after closing and reopening the modal.
- Confirm each selection refreshes the visible remote/branch/tag context.
- Confirm a request cannot be scheduled when the bootstrap manager would use a
  different remote or unsupported Agent Spine tag format.
