# Agent Zero A2A Unifier Adapter DOX

The assembled package is `a2a_format_unifier`; keep this identity in the manifest and Python imports.
`a2a_unified_chat` resolves registered peer aliases, loads only that peer's environment credential,
and persists one context per endpoint in private `.runtime/`. Explicit reset is user-directed.
Delegation routes are configuration, not protocol special cases or proof of device availability.

`helpers/server.py` wraps `DynamicA2AProxy.__call__` in memory after the guarded init hook.
The wrapper preserves native authentication and supports only SendMessage, GetTask, and CancelTask
aliases plus same-request-origin card URLs. Disablement or `inbound_compatibility: false` bypasses it.
Poll submitted/working native tasks without repeating sends (90-second maximum).
Expose the final agent history entry as a status message when absent; interpret
the installed native worker's naive timestamps using its process-local timezone.
Native inbound task contexts remain temporary: protocol IDs do not imply host memory persistence.
Unsupported host signatures degrade without preventing Agent Zero startup. A UI reload activates
the startup hook; allow several minutes for existing integrations before concluding startup failed.

Do not add dependencies, services, blanket server-v1 claims, raw credential arguments, or core edits.
The default config is an example; local routes and private settings must not enter the repository.
Tests and live evidence must distinguish client reply parsing from native reverse initiation.
