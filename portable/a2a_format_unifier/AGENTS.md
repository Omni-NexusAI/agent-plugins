# A2A Format Unifier DOX

## Ownership

- `core/` owns framework-independent format conversion, JSON-RPC client, and ASGI middleware.
- `adapters/agent_zero/` owns Agent Zero tool/config/hooks and its installable documentation.
- `build.py` assembles a self-contained package under `plugins/a2a_format_unifier`.
- `tests/` verifies assembled code, not imports from this source tree.

## Contracts

- Known dialects are A2A 0.3.x, 1.0.x, and the observed FastA2A 0.2.5 profile.
- Unknown versions, bindings, and lossy mappings fail explicitly. Never claim all frameworks or future versions work.
- Never retry a send automatically after parsing failure; the remote agent may already have run it.
- Preserve authentication, errors, task state, metadata, and context. Never bypass native server authentication.
- Agent Zero inbound support is an idempotent in-memory ASGI binding; no shipped source files are edited.
- Native A0 requests bypass the adapter before body reads. Only explicit v1 POST
  requests and the modern card alias opt in; preserve native cards byte-for-byte.
- Keep credentials plugin-private. Never own native A2A_TOKEN, host/profile
  prompt overrides, native peer aliases, or enablement policy outside the plugin.
- Disablement bypasses the inbound wrapper. No separate service or listener is created.
- Keep runtime config, credentials, locks, conversation state, logs, and caches out of the distribution.
- Assemble all shared code into each adapter distribution; never import the monorepo at runtime.
- Keep the assembled plugin, source, catalog, README, and verification record aligned.

## Verification

Run the format/client/middleware tests against a newly assembled package outside the checkout.
Check `build.py --check`, catalog preview, and native tool discovery. Live directions need separate evidence.
Do not reset existing conversations or contact device peers merely to test transport.

## Child DOX

- `adapters/agent_zero/AGENTS.md`: native tool, settings, and server binding contract.
