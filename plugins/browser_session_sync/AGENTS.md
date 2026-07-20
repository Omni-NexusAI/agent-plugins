# Browser Session Sync DOX

## Purpose

This plugin persists native Agent Zero Browser tabs, cookies, and localStorage across runtime restarts.

## Contracts

- Keep all behavior plugin-owned; do not require patches to updater-managed `_browser` files.
- Automatic restore is boot-gated and one-shot. Save events must never reopen tabs.
- Restore through the existing `browser_runtime_started` extension point before native Browser listing; the earlier WebSocket fallback is only for hosts missing that event.
- The current-state manifest is authoritative, including snapshots containing zero tabs.
- Preserve legacy storage-only snapshots and timestamped snapshots for manual recovery.
- Keep save listeners idempotent and saves debounced to avoid duplicate input bindings or browser slowdown.
- Plugin enable/disable is owned by the parent A0 plugin manager; this plugin must not add a second internal enable switch.
- Global restore scope is the default; per-chat scope is optional and must not delete the global current snapshot during chat cleanup.
- Global scope shares the current snapshot across chats, but each chat retains its own native Browser runtime and tab IDs.
- `auto_restore`, `auto_save`, restore scope, chat-delete cleanup, auto-restore tab limits, and cache retention remain independently configurable.
- The settings component must be self-contained per modal mount; do not depend on a global Alpine store or module script execution inside A0's injected `config.html`.
- Settings fields must bind to the parent A0 modal `context.settings`; the native modal `Default` and `Save` buttons are authoritative, while plugin-local controls may only manage cache/session actions such as refresh or delete.
- Keep `thumbnail.png` at the plugin root for marketplace/source catalog use and `webui/thumbnail.png` for installed-plugin UI display.

## Verification

- Run `python -m pytest tests` in an Agent Zero-compatible Python environment.
- Verify a hard restart restores tabs when the Browser panel subscribes.
- Close a restored tab, restart again, and confirm it stays closed.
- Confirm typing emits one character per keypress and routine browsing produces sparse saves.
