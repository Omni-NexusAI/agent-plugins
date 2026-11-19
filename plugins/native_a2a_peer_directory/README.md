# Native A2A Peer Directory

An optional contact list for Agent Zero's built-in `a2a_chat`. It supplies
explicit native peer names and verified LAN/Tailscale addresses in temporary
prompt metadata, so naming a peer does not depend on semantic memory recall.
It does not send, route, authenticate, convert formats, or replace native tools.
A2A Format Unifier remains a separate optional cross-framework adapter.

Copy this complete folder into `usr/plugins/` and configure `config.json`
before enabling it through the normal plugin manager. No restart or core/profile
edit is required. Empty configuration is inert. Example addresses are placeholders:

```json
{
  "peers": [{
    "name": "LaptopA0",
    "framework": "agent-zero",
    "card_name": "Agent Zero",
    "card_provider": "Agent Zero",
    "protocol_version": "0.2.5",
    "verified_at": "2026-11-05",
    "lan_url": "http://192.168.1.20:5027/a2a",
    "tailscale_url": "http://100.64.0.20:5027/a2a",
    "secret_name": "A2A_PEER_LAPTOP_A0_TOKEN"
  }]
}
```

Verify both addresses belong to the intended native Agent Zero and independently
check its Agent Card and authentication first. Identity metadata is operator
configuration, not cryptographic proof or a continuous health check. Store the
dedicated credential in Agent Zero's existing native secret store; this plugin
stores only its reference name and renders `§§secret(...)` in the native URL.
Do not include raw tokens. Runtime configuration and toggles are not distributed.

The directory describes LAN preference and a Tailscale alternative for the same
peer; it implements no failover or retries. Never repeat an accepted or uncertain
send on the alternative address. Native secret resolution and task polling remain
the host's responsibility. Hermes must have its own distinct identity and address.

Supported scope is explicit IPv4 private-LAN/Tailscale contacts with `/a2a` and
the same published port. Hostnames, public endpoints, alternative transports and
automatic peer discovery are outside this initial package. Invalid or ambiguous
configuration injects no directory. Disabling/removing it leaves native transport
unchanged; temporary metadata clears on the next prompt. Older chat messages are
retained and can still contain historical contact information.

Run `python plugins/native_a2a_peer_directory/tests/test_directory.py` from the
monorepo root. See [VERIFICATION.md](VERIFICATION.md) for live acceptance limits.
