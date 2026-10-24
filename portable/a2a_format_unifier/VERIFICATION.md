# Verification record

Date: 2026-10-24. Development version: 0.1.0.

## Automated and packaging evidence

- 19 focused unittest checks passed on Windows Python 3.14.7 and Linux Python
  3.12.4. Each run imported an independently assembled package outside this
  checkout. No monorepo import dependency was present in that distribution.
- Cases cover the observed Hermes response; known version negotiation;
  role/state/ID and timestamp conversion; data, metadata, and file fixtures;
  unsupported/lossy formats; persisted context and explicit reset; corrupt
  state; failures/empty replies; task polling without repeated sends; native
  auth failure passthrough; legacy passthrough; mounted card endpoint; and
  pending-task polling with the completed history exposed as a reply.
- `build.py --check`: assembled package matches portable source.
- Python AST parse: all nine portable Python files passed.
- `sync-to-repos.py --plugin a2a_format_unifier`: valid catalog, development
  package, 13 tracked distribution files, no standalone release destination.
- `git diff --cached --check`: passed. Staged diff contained no matched known
  local A2A credentials and no private config/runtime paths.

## Live evidence

Runtime: Agent Zero v2.0 (`agent0ai/agent-zero:v2.0`), observed FastA2A card
version 0.2.5, and the installed Windows Hermes A2A 1.0 gateway.

- Agent Zero's native tool resolver selected `a2a_unified_chat`.
- A real authenticated call through that tool consumed a Hermes reply.
- A follow-up recalled a marker from the same conversation; persisted context
  was unchanged. This verifies the requested outbound Hermes continuity.
- The final installed Python code matches the assembled package. Local device
  aliases `quest3`, `android-phone`, and `laptop3080` remain configured through
  Hermes, and one saved context remains. The Hermes Bridge MCP entry is absent.
- The inbound hook loaded, retained native authentication, and corrected the
  card from an internal localhost endpoint to the reachable caller endpoint.
- The first native Hermes reverse attempt reached Agent Zero and exposed the
  missing required legacy `acceptedOutputModes` configuration. That was fixed.
- Installed FastA2A source inspection showed its send method returns a submitted
  task immediately, ignores blocking configuration, and stores final text in
  history with a naive local timestamp. The inbound wrapper now handles those
  specific behaviors; the regression passes in both isolated test runs.
- After the existing Time Travel watcher finished, native Hermes `a2a_call`
  successfully submitted a task through the installed adapter. Agent Zero
  began its knowledge-store initialization but did not finish the task within
  the adapter's 90-second completion window; the call returned HTTP 504.
- A subsequent native Hermes HTTP `GetTask` request retrieved that same task
  with `TASK_STATE_SUBMITTED`, verifying reverse request/reply format conversion
  without repeating the send. No completed agent reply was observed. An
  unauthenticated native request still returned HTTP 401.
- No Hermes adapter was installed, and no unrelated integration was changed to
  accelerate startup. The reverse direction is accepted and pollable, but a
  completed reverse conversation remains unverified.

## Limits of this evidence

Device aliases are configuration evidence, not live delivery tests to those
devices. File/data transfer is fixture-tested only. No Agentspine integration,
arbitrary framework compatibility, streaming conversion, or future-version
support is claimed. Native Agent Zero inbound tasks retain their temporary
context lifecycle; protocol context IDs alone do not establish host recall.

FastA2A's required configuration fields were checked against its
[current type documentation](https://github.com/datalayer/fasta2a/blob/main/_autodocs/types.md)
and the actual installed runtime, whose immediate task-return behavior is the
authority for the Agent Zero binding.
