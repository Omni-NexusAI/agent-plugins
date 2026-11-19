# A2A Format Unifier implementation plan

## November 5 repair

Restore direct native peer selection by removing demonstrated obsolete runtime
memory guidance separately, with private backups and native memory APIs. Do not
ship memory edits, peer aliases or routes as plugin behavior. Verify native
LAN and Tailscale replies with compatibility disabled before activating it.

Add a plugin-owned lifecycle hook so enabling the adapter in a running Agent
Zero installs its guarded bindings without a process restart. Preserve the
native parser, endpoint, credentials and exactly-once send semantics. Test
disabled/unrelated-change behavior, idempotent activation and unsupported-host
isolation. Recheck real native and Hermes replies after activation. Keep this
PR draft and unmerged.

Create a framework-independent format core and an Agent Zero adapter. Assemble
a self-contained `plugins/a2a_format_unifier` distribution that imports no
monorepo paths at runtime. Keep device routes and credentials configurable.

The observed failure was an older FastA2A client rejecting Hermes A2A 1.0 task,
role, and part fields after authentication and generation had succeeded.

Verify known 0.3/1.0 conversions, errors, context persistence, and native Agent
Zero tool discovery. A live Hermes reply and continuation have passed in the
local prototype. Check reverse initiation independently: Agent Zero's card
advertises an internal localhost endpoint and reports FastA2A protocol 0.2.5.
Do not claim universal future-version compatibility or an unverified direction.

Publish through a draft PR; keep runtime state, credentials, and caches out of
source. Add packaging instructions, owning DOX, catalog entry, and evidence.

## Implemented

Version 0.2.0 replaces the separate chat/routing tool with native-first parser
fallback. No preferred Hermes peer, alias registry or broker delegation remains.
The native tool is unchanged; received incompatible foreign replies may be
adapted after validation failure. Native and foreign live checks each completed
with one send at the selected endpoint; native A0 needed zero adaptations.
See the current verification record above the historical 0.1.x design notes.

Version 0.1.1 adds strict containment: native traffic bypass, plugin-private
credentials, no native prompt override, explicit broker aliases, disabled-state
preservation, and 26 passing checks. The authorized native laptop ping completed
with the plugin disabled. The prior 0.1.0 result below is historical.

The portable core, Agent Zero adapter, self-contained distribution, catalog,
installation guide, and verification record are present. Nineteen isolated
checks pass on Windows and Linux. Native outbound reply/continuation passed;
reverse submission and GetTask conversion passed, but completion exceeded the
90-second wait during Agent Zero's knowledge-store initialization. No Hermes
plugin was installed. See `VERIFICATION.md` for the evidence boundaries.
