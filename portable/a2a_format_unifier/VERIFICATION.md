# Verification record

## 0.2.0 native-first fallback - October 26, 2026

- Removed the agent-facing a2a_unified_chat tool and its prompt, all preferred
  peer defaults, the peers/routes registry, and broker delegation behavior.
- The only chat entry point is the original a2a_chat. Plugin-owned integration
  calls the original client/parser first, adapting an already received reply
  only after native validation fails on a known non-Agent-Zero wire profile.
- Native A0 replies, authentication/network errors, unknown formats and selected
  endpoints are not substituted or silently repaired. Converted replies are
  validated again using the native schema. No send is retried.
- Optional credentials are scoped to an explicitly selected exact URL, with
  optional expected card-name validation before messages. There are no aliases.
- Linux: 36 checks passed in the installed native Agent Zero/FastA2A environment.
  Windows: 28 portable checks passed; 8 native integration checks were skipped
  because that host Python does not contain the Agent Zero runtime.
- Controlled live checks invoked the actual native A2AChatTool.execute with the
  fallback enabled only inside the test process. Laptop Agent Zero returned the
  requested marker after exactly one send, with zero adaptations. Hermes returned
  its requested marker after exactly one send, with two response adaptations
  (send/poll). Both retained the exact selected endpoint. No device relay occurred.
- The persistent plugin toggle remained disabled during both live checks. The
  legacy tool/prompt were absent. The native source files were not overwritten;
  local deployment changed plugin-owned files/configuration only and reloaded
  the UI once to clear loaded legacy tool classes.
- The inspected branch had inherited the earlier incorrect LaptopA0-to-Hermes
  rename, re-enabled the old tool, then selected Hermes directly. New plugin
  code cannot erase those historical messages. This is not evidence that the
  native laptop A0 connection was renamed or moved. Validate routing with a
  fresh request at the intended native endpoint, not the old mistaken alias.

Historical 0.1.x records below describe earlier designs and tests.

## 0.1.1 containment correction - October 26, 2026

- 26 isolated checks passed on Windows Python 3.14 and Linux Python 3.12.
  New regressions cover native card preservation, native large-body bypass,
  explicit modern scope, plugin-private credentials, outside-path rejection,
  and refusal to consume the native A2A_TOKEN variable.
- Native legacy traffic now bypasses before body reads and plugin-config checks.
  Only explicit v1 POST requests and the modern card alias opt in.
- The approved local migration backed up and removed the manual agent-profile
  prompt override, restored the pre-install absence of the shared A2A_TOKEN
  entry, and moved the Hermes credential to plugin-private storage.
- Broker aliases now carry a Hermes prefix. The misleading LaptopA0-to-Hermes
  route was removed; this does not create or rename a native A0 registry entry.
- The user's disabled-plugin state was restored after Agent Zero had
  independently re-enabled it in the troubleshooting conversation. One UI
  process reload was performed; no native A2A source file was edited.
- A user-authorized live native desktop-to-laptop Agent Zero ping used the
  original connect_to_agent client and native response extractor. The laptop
  accepted the task, completed it, and returned the expected NATIVE_A0_READY
  marker while the unifier remained disabled. This is actual generated-reply
  evidence for that request/response direction, not just a card check.
- Shared core and assembled distribution match; catalog preview validates
  15 package files. The prior 0.1.0 evidence below is historical.

### Separate greeting-loop observation

The Laptop renaming transcript retained a startup Hello topic and the correct
rename request. Its first task call understood the rename, then subsequent
DeepSeek chat-completions turns answered the older greeting. After a stop/nudge
and a user model change, GLM resumed the rename. The earlier A2A investigation
loop also used DeepSeek. These are observations and a correlation, not proof
of a specific model/provider fault. No stored Responses continuation was used,
and no A2A request produced the greeting steps. The containment repair addresses
the demonstrated disabled-tool/routing interference; it does not claim to
resolve the greeting behavior's exact cause.
An offline replay through the installed history serializer and model-message
converter preserved the rename request and correct role alternation before all
four incorrect greeting turns. No provider request was made for that check;
the exact wire requests from the historical failing turns were not captured.

## Historical 0.1.0 evidence

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
