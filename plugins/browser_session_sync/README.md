# Browser Session Sync

Work-in-progress Agent Zero plugin that preserves native Browser tabs, cookies,
and localStorage across hard container restarts.

Includes a plugin thumbnail at `webui/thumbnail.png` for installed plugin
lists and a matching root `thumbnail.png` for marketplace/catalog surfaces.

## Behavior

- Restores the latest current-state snapshot into native tab registration before
  the Browser viewer or agent receives its first tab list.
- Tracks tab loads and closes with debounced, atomic snapshots.
- Treats an empty tab set as authoritative, so closed tabs stay closed.
- Restores the latest global browser state by default across chats; each active
  chat receives its own native runtime populated from that shared snapshot.
- Can be switched to per-chat scope when an isolated browser cache is needed.
- Deletes a chat's browser cache when that chat is removed by default, while preserving the global current state.
- Keeps timestamped snapshots for explicit manual recovery.
- Provides manual `browser_session_save` and `browser_session_restore` tools.
- Stays plugin-owned and does not patch updater-managed Agent Zero files.

## Configuration

Enable or disable the plugin from Agent Zero's parent plugin menu. The plugin's
own settings control restore, save, scope, and retention behavior.

```yaml
auto_restore: true
auto_save: true
session_scope: global
delete_on_chat_remove: true
max_auto_restore_tabs: 0
max_saved_sessions: 500
max_cache_mb: 1024
```

`max_auto_restore_tabs: 0` means automatic restore uses the native Browser tab
limit. Snapshots still save every open tab for manual recovery.

## Install

Install this repository as the `browser_session_sync` Agent Zero plugin, or copy
its contents to `/a0/usr/plugins/browser_session_sync`. Restart Agent Zero after
installation so lifecycle extensions are loaded.

Saved browser state is written under `/a0/usr/browser_sessions` and is not part
of the plugin repository.

## Status

This is a WIP release. Keep production snapshots backed up while testing browser
runtime and WebUI compatibility across Agent Zero updates.

## Tests

Run from an Agent Zero environment where the `helpers` and `usr` packages are
available:

```bash
python -m pytest tests
```
