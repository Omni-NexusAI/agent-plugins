# Initial Greeting Guard

Version 0.0.2. This separate plugin marks only newly created native synthetic
welcome records from two inspected Agent Zero initializer implementations.
It omits the verified pair from model-facing history when a real user request
follows. The visible welcome, original stored content, genuine greetings, tool
receipts, old unmarked conversations and unrelated plugins remain unchanged.

Copy this complete folder into `usr/plugins/initial_greeting_guard` and use the
normal plugin manager. A supported own-plugin change refreshes only this
plugin's pure helper namespace, allowing activation without a service restart
when Windows bind-mount writes do not reach native file watchers.

The guard verifies the executing initializer's exact source path/hash, same
agent identity, empty initial log, record sequence/roles, native non-LLM metadata,
record IDs and content hashes. The reviewed v2.15 initializer additionally
requires exactly its native `initial_seed: true` metadata, which is preserved.
Unknown implementations and modified/incomplete provenance fail closed. No
keyword filtering, native function replacement or history migration is used.

The inspected initializer fingerprints are `92dc7257...` (legacy) and
`6f481bc1...` (v2.15); complete hashes are in helpers/seed.py. A new host version
requires source review and native tests before extending that allowlist.

Run `tests/test_guard.py` from the framework runtime with the package parent on
PYTHONPATH. Optional A0_AUDIT_CHAT_IDS selects existing unmarked chats for an
additional read-only serialization check; no private chat IDs ship as defaults.
Native initializer/history/model-message and prompt-grouping checks are offline.
This is a synthetic-seed mitigation, not a universal task-loss repair. Genuine
greeting -> later task -> actual tool receipt -> correct final answer remains
a separate live acceptance gate. Disable the plugin to restore ordinary native
model-facing history; no stored message deletion is required.
