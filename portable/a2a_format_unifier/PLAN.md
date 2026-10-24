# A2A Format Unifier implementation plan

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

The portable core, Agent Zero adapter, self-contained distribution, catalog,
installation guide, and verification record are present. Nineteen isolated
checks pass on Windows and Linux. Native outbound reply/continuation passed;
reverse submission and GetTask conversion passed, but completion exceeded the
90-second wait during Agent Zero's knowledge-store initialization. No Hermes
plugin was installed. See `VERIFICATION.md` for the evidence boundaries.
