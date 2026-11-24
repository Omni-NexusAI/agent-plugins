# Native A2A Peer Directory DOX

This optional companion supplies explicit native Agent Zero contact metadata
through the supported message_loop_prompts_after extension. It is separate from
A2A Format Unifier. Never put native discovery or aliases in that adapter.

Use only extras_temporary; the host clears it after every prompt. No persisted
history, profile prompt, core file, transport class, tool or credentials are
replaced. No new tool, automatic discovery, network probe, preferred peer,
endpoint rewrite, relay, credential injection or message retry belongs here.

Runtime config owns an explicit peers list. Each entry has name, framework,
card_name, card_provider, protocol_version, verified_at, lan_url, tailscale_url
and secret_name. Card identity must be independently verified before configuring
it. URLs are restricted to IPv4 RFC1918 LAN and Tailscale CGNAT addresses,
an explicit identical port, and /a2a. Secret references must use A2A_PEER_*;
no token value, shared A2A_TOKEN or embedded token URL is accepted.

Validate all entries before injecting any metadata; duplicate names or malformed
configuration fail closed. Blank config is inert. Native a2a_chat remains the
only message path. Disabling removes the temporary directory from subsequent
prompts; direct native URL calls do not depend on this package or Unifier.

Run tests/test_directory.py. Live acceptance requires an ordinary named-peer
request with no URL supplied, the intended native endpoint, one send, an actual
remote acknowledgment and a correct final answer. Memory retrieval, prompt
presence, a card, or a scripted transport call alone do not pass that gate.
