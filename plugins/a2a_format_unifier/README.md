# A2A Format Unifier for Agent Zero

Version 0.2.0 is a native-first format fallback. It has **no separate chat tool,
preferred peer, device alias registry, broker routing, or Hermes default**.
Agent Zero's built-in `a2a_chat` chooses the intended endpoint, sends the message,
validates replies, and owns its conversation state.

## Behavior

- The plugin delegates to the original native client first.
- A compatible reply is returned unchanged. Agent Zero peers are never adapted.
- Only after the native validator rejects a received non-Agent-Zero reply may
  known A2A 0.3/1.0 fields be normalized and validated again by the native schema.
- Adaptation uses that same HTTP response at that same endpoint. It does not
  resend a message, select Hermes, follow a card's alternate URL, rename peers,
  mask an authentication failure, or retry a failed task elsewhere.
- The normal native conversation/context machinery remains in control. Hermes
  may independently enforce its configured peer-scoped server conversation.

The inbound adapter remains limited to the modern card alias and explicit
`A2A-Version: 1.0` POSTs. Native legacy requests/cards bypass it. Native token
authentication remains authoritative. This is not a complete A2A 1.0 server.

## Install

Copy this complete `a2a_format_unifier` folder into persistent `usr/plugins/`,
enable it when desired, and reload the UI process once. The portable source
folder alone is not installable. No native source, shared environment, agent
profile prompt, provider setting, or model history needs modification.

Default configuration:

```json
{
  "outbound_fallback": true,
  "inbound_compatibility": true,
  "endpoints": []
}
```

Use the built-in `a2a_chat` with the exact endpoint of the intended agent.
An Agent Zero on a laptop and a Hermes agent on that laptop are different
agents; a machine name alone must never substitute one for the other.

## Optional endpoint-scoped credentials and identity check

A cross-framework endpoint requiring its own bearer can be configured explicitly.
This is an allowlist for that exact URL, not a peer preference or routing table:

```json
{
  "outbound_fallback": true,
  "inbound_compatibility": true,
  "endpoints": [{
    "url": "http://host.docker.internal:9900/",
    "framework": "hermes",
    "expected_agent_name": "windows-desktop",
    "token_file": ".private/hermes.token"
  }]
}
```

The URL and advertised name are installation-specific examples. The credential
is attached only when the native caller has already selected that exact endpoint;
explicit caller credentials are preserved. A mismatched advertised name stops
before sending an agent message. Card names are advertised identity information,
not cryptographic identity proof. No alias, text matching, or endpoint substitution
is performed. Paths and ports must match; invalid unrelated entries are ignored.

Keep the token in this plugin's private file. Outside paths/symlinks are refused.
An explicitly configured dedicated `token_env` is an alternative, but native
`A2A_TOKEN` is reserved and refused. This plugin never sets shared credentials.
Without a matching credential entry, native authentication behaves normally.

## Disablement and limits

Respect the user's disabled state. Never enable or reproduce this plugin to
perform an ordinary native Agent Zero task. Disabling bypasses new native client
connections and inbound handling; reload to remove installed in-memory wrappers.
All integration code belongs to this plugin; no host source file is overwritten.

Fallback is restricted to received parse failures and known non-native profiles.
Authentication/network errors, malformed native A0 replies, unknown versions,
and lossy conversions remain failures. Requests are not retried with a different
method when the peer rejects the native method. Streaming, gRPC/REST bindings,
OAuth and push conversion are outside this release's tested scope. File/data
conversion is fixture-tested; live reply evidence is text-only.

## Migration from 0.1.x

Remove/archive the old `tools/a2a_unified_chat.py` and its matching prompt when
upgrading an installed folder. There is no replacement chat tool. Remove old
`peers`/`routes` configuration; retain only explicitly required endpoint-bound
credentials. Preserve private credentials and old conversation state for recovery.

Earlier manual installations may also have added a native agent-profile prompt
note and a shared A2A_TOKEN entry. Back up and undo only those verified changes;
restore independently verified prior host state and reload when safe. Keep all
future compatibility behavior within this plugin. Branches inherit old messages,
including incorrect routing claims; removing a plugin cannot erase that history.
Validate fresh requests against the intended native endpoint rather than copying
an earlier mistaken Hermes association.

The shared core, assembly command, tests and precise evidence are documented in
`portable/a2a_format_unifier/` in the Agent Plugins monorepo. This assembled
package includes its core and MIT license and needs no monorepo at runtime.