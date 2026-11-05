# Agent Zero native-first A2A fallback DOX

Package identity is a2a_format_unifier. There is no chat tool, peer alias
registry, broker route, or preferred endpoint. Native a2a_chat remains the
only agent-facing chat path. Do not add a model prompt advertising Hermes.

helpers/native_client.py installs guarded in-memory wrappers around the native
AgentConnection constructor/card reader. Original native validation runs first.
Only a caught native ValidationError on an already received, successful,
non-Agent-Zero response can invoke the shared fallback converter. Revalidate
converted replies with the native schema. Never resend a message or change the
selected URL, method, task ID, context, or intended peer. Preserve native errors.

Optional endpoint-scoped credentials match exact URL/port/path and may check the
advertised card name before messages. They are not a routing table. Credentials
are plugin-private; never read or mutate native A2A_TOKEN for this integration.
No native/profile source, global credentials, memories or model settings are edited.

The inbound server binding is still opt-in for v1 POSTs and the modern card alias.
Native legacy cards/requests bypass it. Disabling bypasses new connections and
requests; reload removes in-memory wrappers. Respect the user's toggle.

helpers/bindings.py owns guarded startup and live activation. The supported
helpers.plugins.after_plugin_change end hook installs bindings only for this
plugin or a full refresh, after cache invalidation. Disabled, unrelated and
failed changes do not activate it. Both binding installers remain idempotent;
unsupported client/server interfaces fail independently. No service restart,
new listener, native source edit or model prompt is required to enable it.

Native tests must show no adaptation on compatible or malformed Agent Zero
replies, native parsing before fallback, one send only, unchanged selected
endpoint, no auth-error fallback, identity mismatch before sends, unknown-format
failure, and original behavior when disabled. Do not turn a card check into
proof of a generated live reply. Branch history can retain old incorrect routes;
never silently edit user conversations to hide that.
