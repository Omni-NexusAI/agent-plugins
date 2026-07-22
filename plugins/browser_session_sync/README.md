# Browser Session Sync

Browser Session Sync keeps Agent Zero's built-in Browser panel where you left
it. It saves open tabs, cookies, and localStorage, then restores them after an
Agent Zero restart or container reset.

Use it when you want browser logins, active tabs, and working context to survive
between A0 sessions without asking the agent to manually restore a saved
browser state.

## What It Does

- Restores saved Browser tabs automatically when the native Browser runtime
  starts.
- Saves cookies and localStorage so sites can keep their logged-in state.
- Tracks the current Browser state as tabs load, navigate, or close.
- Preserves closed tabs as closed. If you close a restored tab, that newer
  state is saved and the tab should not come back on the next restart.
- Supports a shared global browser session by default, with an optional
  per-chat mode for isolated sessions.
- Shows saved sessions in plugin settings, including tab URLs, titles, cookies,
  storage origins, file size, and saved time.
- Provides manual `browser_session_save` and `browser_session_restore` tools
  for recovery or explicit session restore.

## How To Use It

1. Install and enable **Browser Session Sync** from Agent Zero's plugin manager.
2. Open the Browser panel and browse normally.
3. Leave tabs open, sign in to sites, or close tabs as usual.
4. Restart Agent Zero or reset the container.
5. Open the Browser panel again. The plugin restores the latest saved state
   automatically when the Browser runtime starts.

The plugin is designed to stay out of the way after startup. Once a session has
been restored for the current Browser runtime, it switches to tracking mode and
only saves state changes.

## Settings

Open **Settings > Plugins > Browser Session Sync** to manage behavior and saved
sessions.

### Auto Restore

Automatically restores the latest saved browser state when the Browser runtime
starts.

Turn this off if you want to keep saving sessions but prefer to restore them
manually with the `browser_session_restore` tool.

### Auto Save

Automatically saves the current Browser state while you browse.

Turn this off if you only want manual saves. When disabled, the plugin will not
keep the cache updated as tabs change.

### Session Scope

Controls which saved state automatic restore uses.

- `global`: default. All chats share the latest global Browser state. Each chat
  still gets its own native Browser runtime, but the restored tabs come from the
  shared global snapshot.
- `chat`: saves and restores Browser state per chat/context. Use this when each
  chat should have an isolated Browser session.

### Delete Chat Cache When Chat Is Removed

Deletes saved per-chat Browser snapshots when that chat is removed.

This does not delete the global current session. It only cleans up snapshots
that belong to the removed chat/context.

### Maximum Auto-Restore Tabs

Limits how many saved tabs are automatically reopened at startup.

- `0`: use the native Browser tab limit.
- Any positive number: restore up to that many tabs automatically.

This only limits automatic reopening. The snapshot can still store more tabs
for manual recovery.

### Maximum Saved Sessions

Controls how many session snapshot files are kept.

When the limit is exceeded, the plugin removes older snapshots first and repairs
the manifest so stale pointers do not remain.

### Maximum Cache Size

Controls the total size of saved Browser session files, in MB.

Use this to keep `/a0/usr/browser_sessions` from growing too large. If the cache
is over the limit, older snapshots are removed until the cache is within the
configured size.

## Saved Sessions

The settings page includes a **Saved Sessions** table. Use it to inspect and
manage the cache.

Each row shows:

- snapshot filename
- chat/context id when available
- whether it is the current or global latest snapshot
- tab count
- cookies and storage origins
- file size
- saved time
- expandable tab URLs and titles

You can delete individual sessions or clear all saved sessions from this view.

## Agent Usage

When a persisted Browser session may already exist, agents should list Browser
tabs before opening a new tab. Restored tabs are native Browser tabs and should
appear in the Browser tool's tab list with normal `browser_id` values.

Manual tools are available when an explicit recovery action is needed:

- `browser_session_save`: saves the current Browser state now.
- `browser_session_restore`: restores a selected saved session on request.

## Where Data Is Stored

Saved Browser sessions are stored in:

```text
/a0/usr/browser_sessions
```

The plugin repository does not include saved sessions, cookies, or user browser
data. Those files stay in the local A0 environment.

## Install

Install this repository as the `browser_session_sync` Agent Zero plugin, or copy
its contents to:

```text
/a0/usr/plugins/browser_session_sync
```

Restart Agent Zero after installation so lifecycle extensions are loaded.

## Notes

- Browser Session Sync uses plugin hooks and does not patch updater-managed
  Agent Zero Browser files.
- Some sites may still require a fresh login after restart depending on their
  own security rules, token expiry, or device checks.
- If the Browser panel still shows old data after updating the plugin, refresh
  the A0 page or restart Agent Zero so plugin metadata and assets reload.

## Marketplace Assets

The repository includes:

- `thumbnail.png`: marketplace/catalog thumbnail.
- `webui/thumbnail.png`: installed plugin thumbnail used by Agent Zero plugin
  UI surfaces.
