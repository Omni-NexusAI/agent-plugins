# Browser Session Sync

Startup migration and agent initialization install the native runtime adapter
synchronously, matching Agent Zero's dispatchers. Asynchronous initialization
hooks prevent boot or agent creation even when the runtime adapter passes tests.

Browser Session Sync keeps recovery snapshots of Agent Zero Browser tabs,
cookies and localStorage. On Agent Zero 2.11, native persistence owns the
shared sign-in profile and normal tab restoration.

Use it when you want browser logins, active tabs, and working context to survive
between A0 sessions without asking the agent to manually restore a saved
browser state.

## What It Does

- Uses cached tabs only when native saved tab state is absent. An explicitly
  empty native tab list remains empty.
- Applies cached sign-in automatically only to a demonstrably empty native
  profile, before restored pages navigate. Existing or uncertain profiles
  require manual recovery.
- Saves cookies and localStorage so sites can keep their logged-in state.
- Tracks the current Browser state as tabs load, navigate, or close.
- Preserves closed tabs as closed. If you close a restored tab, that newer
  state is saved and the tab should not come back on the next restart.
- Preserves native chat ownership in snapshots. Global or per-chat cache
  selection does not change native tab scope or isolate the shared sign-in.
- Shows saved sessions in plugin settings, including tab URLs, titles, cookies,
  storage origins, file size, and saved time.
- Provides manual `browser_session_save` and `browser_session_restore` tools
  for recovery or explicit session restore.

## How To Use It

1. Install and enable **Browser Session Sync** from Agent Zero's plugin manager.
2. Open the Browser panel and browse normally.
3. Leave tabs open, sign in to sites, or close tabs as usual.
4. Restart Agent Zero or reset the container.
5. Open the Browser panel again. Native persistence restores its saved tabs;
   the plugin supplies only eligible missing-state recovery.

The plugin is designed to stay out of the way after startup. Once a session has
been restored for the current Browser runtime, it switches to tracking mode and
only saves state changes.

## Settings

Open **Settings > Plugins > Browser Session Sync** to manage behavior and saved
sessions.

### Auto Restore

Enables eligible cache fallback when the Browser runtime starts. Native
persistence remains active independently of this setting.

Turn this off if you want to keep saving sessions but prefer to restore them
manually with the `browser_session_restore` tool.

### Auto Save

Automatically saves the current Browser state while you browse.

Turn this off if you only want manual saves. When disabled, the plugin will not
keep the cache updated as tabs change.

### Session Scope

Controls which saved state automatic restore uses.

- `global`: default. Use the latest shared cache as the fallback candidate;
  each tab retains its original chat owner.
- `chat`: limit fallback tabs to the requesting chat. Sign-in remains shared
  on current hosts; this setting does not create a separate profile.

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

List snapshots with `list: true`, then choose `filename` explicitly. Manual
recovery applies that snapshot's cookies to the shared sign-in profile and
fills missing localStorage entries; existing localStorage values are retained.
Only the requesting chat's owned tabs reopen, with duplicate URLs skipped.
Historical tabs without ownership are eligible only when their snapshot
filename identifies the requesting chat. No profile or cache is cleared.

Older hosts retain the legacy startup hooks and controls. Shared-runtime hosts
use a guarded plugin-local startup adapter; no native source files are edited.

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
