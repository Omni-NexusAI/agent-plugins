# Browser Session Sync DOX

## Purpose

This plugin persists native Agent Zero Browser tabs, cookies, and localStorage across runtime restarts.

## Contracts

- Keep all behavior plugin-owned; do not require patches to updater-managed `_browser` files.
- Automatic restore is boot-gated and one-shot. Save events must never reopen tabs.
- On shared-runtime hosts, `helpers/native_adapter.py` wraps native startup from startup-migration/agent-init hooks. Capture profile emptiness after native legacy adoption, then apply fallback before native scoped navigation. Legacy runtime-start/WebSocket hooks remain for older hosts.
- The current-state manifest is authoritative, including snapshots containing zero tabs.
- Preserve legacy storage-only snapshots and timestamped snapshots for manual recovery.
- Keep save listeners idempotent and saves debounced to avoid duplicate input bindings or browser slowdown.
- Plugin enable/disable is owned by the parent A0 plugin manager; this plugin must not add a second internal enable switch.
- Global restore scope is the default; per-chat scope is optional and must not delete the global current snapshot during chat cleanup.
- Native persistence owns the shared profile and normal tabs. Never overwrite a nonempty or uncertain profile automatically. Cached tabs are fallback only for truly absent native state; corrupt or explicitly empty state is not absence.
- Snapshots retain per-tab chat ownership. Shared-runtime operations execute on the owning worker with request context set/reset. Do not reassign unowned historical tabs from another chat.
- Shared snapshots survive chat deletion. Global cache scope does not change native tab scope or isolate shared sign-in.
- `auto_restore`, `auto_save`, restore scope, chat-delete cleanup, auto-restore tab limits, and cache retention remain independently configurable.
- The settings component must be self-contained per modal mount; do not depend on a global Alpine store or module script execution inside A0's injected `config.html`.
- Settings fields must bind to the parent A0 modal `context.settings`; the native modal `Default` and `Save` buttons are authoritative, while plugin-local controls may only manage cache/session actions such as refresh or delete.
- Keep `thumbnail.png` at the plugin root for marketplace/source catalog use and `webui/thumbnail.png` for installed-plugin UI display.

## Verification

- `TODO.md` records deferred startup-performance and saved-session history work; publication does not authorize implementing those follow-ups.

- Run `python -m pytest tests` in an Agent Zero-compatible Python environment.
- Tests must stub host config writes and use temporary snapshot directories; `tests/conftest.py` provides that boundary. Never run fixture settings against the deployed plugin.
- Startup migration and agent initialization use the host synchronous dispatcher: both `execute` methods must be synchronous and return no awaitable. Test through `call_extensions_sync`, not only the runtime adapter.
- Verify a hard restart restores tabs when the Browser panel subscribes.
- Close a restored tab, restart again, and confirm it stays closed.
- Confirm typing emits one character per keypress and routine browsing produces sparse saves.
