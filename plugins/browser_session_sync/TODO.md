# Browser Session Sync follow-ups

These are deferred work requested after acceptance of the Agent Zero 2.11
compatibility fix. They are not part of the current implementation.

- [ ] Measure Agent Zero startup with this plugin enabled and disabled, with
  automatic recovery enabled and disabled. Separate plugin initialization,
  snapshot lookup/recovery, native Browser startup and host filesystem delays.
  Optimize demonstrated plugin costs without changing native persistence,
  losing sign-in data or moving recovery after restored-page navigation.
- [ ] Audit and clarify selection of a specific saved session, including older
  snapshots, instead of implicitly choosing only the latest. Manual restoration
  already accepts a filename; verify what the settings UI exposes before
  designing new controls. Make session identity, save time and tab contents
  clear, and allow deliberate restoration whenever needed.
- [ ] Make history retention predictable: restoring a saved session must not
  consume or delete it. Define explicit retention/protection for user-selected
  sessions, explain any expiry or cleanup, and avoid silent disappearance.
  Preserve chat ownership and clearly describe shared sign-in effects.
