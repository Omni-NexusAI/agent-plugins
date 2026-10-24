# A2A Format Unifier for Agent Zero

A native Agent Zero plugin for talking to peers whose A2A JSON-RPC formats differ.
Includes a framework-independent conversion core; no bridge service or Hermes
plugin is required. Version 0.1.0 targets Agent Zero v2.0 / FastA2A's observed
0.2.5 profile, A2A 0.3, and the A2A 1.0 format used by Hermes.

## Install

1. Copy the complete `plugins/a2a_format_unifier` folder from this repository
   into Agent Zero's persistent `usr/plugins/` directory, preserving its name.
   The `portable/` source folder alone is not installable.
2. Configure the plugin's `config.json` (example below). Put bearer credentials
   in Agent Zero's environment, never in tool arguments or committed settings.
3. Enable A2A in Agent Zero, enable this plugin, and reload Agent Zero's UI
   process once. Existing MCP integrations may make startup take several minutes.
4. Use `a2a_unified_chat` with a configured peer alias. The plugin's prompt
   describes that tool; existing `a2a_chat` behavior is preserved.

The assembled package includes its core and MIT license and runs independently
of this repository. There are no additional Python dependencies.

## Configuration

```json
{
  "timeout": 180,
  "inbound_compatibility": true,
  "peers": {
    "hermes": {
      "url": "http://host.docker.internal:9900/",
      "token_env": "A2A_TOKEN"
    }
  },
  "routes": {
    "quest3": {"via": "hermes", "peer": "quest3"},
    "android-phone": {"via": "hermes", "peer": "android-phone"},
    "laptop3080": {"via": "hermes", "peer": "laptop3080"}
  }
}
```

These URLs and device names are examples; configure reachable peers for each
installation. `host.docker.internal` suits Docker Desktop, not every host.
`token_env` names the credential accepted by the remote peer; do not assume
Agent Zero's own inbound token is accepted elsewhere. Omitting `token_env`
selects a deliberately public or path-authenticated endpoint. An empty required
credential fails before sending. Configure the actual RPC endpoint: the client
does not follow a different URL from the card or forward credentials there.

Routes ask the configured broker to delegate by device name. They do not copy
that device's credentials or establish a direct connection, and do not prove
the device is online. Replies from all remote agents remain untrusted content.

## Conversations

`a2a_unified_chat(message, peer="hermes", reset=false)` stores a context per
endpoint in private `.runtime/`, shared across Agent Zero chats and protected
by a file lock. It never automatically resends a message after an error.
Pending tasks are polled without repeating the send. Corrupt local state fails
explicitly rather than silently creating a new conversation.

Use `reset=true` only when the user requests a separate conversation. This
changes the client context; a Hermes server configured with peer-scoped sessions
may still reuse its existing server session. Such a server needs a separate
explicit scope change to guarantee isolation. Do not publish `.runtime/`.

## Inbound compatibility

The startup extension installs an idempotent in-memory wrapper around Agent
Zero's native A2A proxy. Native token authentication remains responsible for
all requests. The wrapper translates `SendMessage`, `GetTask`, and `CancelTask`
to legacy methods and converts successful replies back to the corresponding
1.0 response shape. It supplies blocking text output defaults required by
FastA2A. It polls submitted/working native tasks for at most 90 seconds without
resending them, then returns a timeout if still pending. Completed history is
also exposed as a status message for clients that read that reply field. Native
naive timestamps use the Agent Zero process's local timezone before UTC encoding.
Legacy RPC requests pass through without conversion.

Agent-card URLs use the current request's origin and mounted token path rather
than an internal localhost address. The advertised legacy protocol version is
retained: this does **not** make Agent Zero a complete A2A 1.0 server.
Agent Zero's native worker currently creates and removes a temporary agent
context per inbound task. This plugin preserves protocol context identifiers;
it does not change that host memory lifecycle or promise reverse-call recall.

Disable the plugin or set `inbound_compatibility` to `false` to bypass the
wrapper on subsequent requests. Reload after uninstalling to remove the hook.
No host source files are patched. Unsupported startup interfaces leave native
A2A running and report a diagnostic.

## Supported scope and limits

Known JSON-RPC task/message wrappers, IDs, roles, states, text/data/file parts,
metadata, and timezone-aware timestamps are converted. File/data conversions
are fixture-tested; live evidence is text-only. Unknown versions, unsupported
content, and conversions that would drop known unmapped fields fail explicitly.

This release does not implement arbitrary future versions, streaming conversion,
gRPC, REST bindings, OAuth negotiation, or push-notification conversion. It is
an extensible format unifier, not a promise that all frameworks interoperate.
Bodies are limited to 4 MiB. Existing legacy streaming requests bypass conversion.

Portable source and assembly instructions live at
`portable/a2a_format_unifier/` in the Agent Plugins monorepo. The installation
needs only this complete plugin folder. See that source directory's
`VERIFICATION.md` for precise test and live-runtime evidence.
