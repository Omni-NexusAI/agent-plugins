# Agent Zero package DOX

This directory is assembled into `plugins/system_1`. Agent Zero hooks, UI, and
API routes live here; the embedded `helpers/system_1_core/` is copied from the
portable core. Do not edit the assembled package directly. Run `assemble.py`
and compare its output. The host retains execution authority, embedding vectors,
and intervention handling.

The Main timeline uses `before_main_llm_call` to create one native Info step
per eligible System 1 decision; `helpers/timeline.py` updates it after routing.
The `hist_add_tool_result` extension observes only a pending System 1 action's
host-recorded result, masks it with the host secrets manager, then the next
model iteration may make a bounded choice. It fails closed if masking fails.
The result observer must never alter host history or block tool completion.
The final-response completion hook rejects unexpected parsed response arguments
for the current System 1 monologue. Agent Zero may repair malformed JSON into
a truncated `text` plus stray fields; request at most two complete formatting
retries from Main using existing evidence, then return an explicit failure.
Replace the already-streamed partial response bubble when deferring completion.
Valid singleton `text` or `message` answers pass unchanged. Pending parallel
jobs take precedence and do not spend the formatting retry budget.
This post-execution guard covers successfully executed split-field responses;
missing or non-string response content stays on the native host repair path.
Deferred bubbles carry private nonterminal metadata because the host marks
response records finished even when the plugin asks its loop to continue.
The action loop uses per-monologue state, an action count cap, and no replay of
action IDs. It withholds result content from the decision service unless the
action explicitly opts in, and returns observed content directly to the user
only with a separate action opt-in. Recheck both permissions and the exact
action definition immediately before the next decision. A guarded
argument binding may use an unambiguous validated request field or a field
from a complete masked JSON result of an action that opted into result bindings.
Unknown shapes, truncated results, revoked permissions, or stale action
definitions hand off to Main. A raw MCP result is never the final user answer.
The timeline records a separate observation marker after a successful host
result, or a failure marker after a failed host result, without copying its
content or arguments. A failed result is never decision or binding evidence.
If an eligible action falls below the configured confidence threshold, the
handoff detail says so rather than claiming that no action was eligible. The
same S1 step names the proposed host tool without presenting it as an executed
action; handoffs without a proposed tool display `None`. Keep tool arguments,
request content, and credentials out of the timeline.
When System 1 chooses `wait_main` with independent actions offered, record the
number offered and actual wait duration. An offered action is policy eligible,
not necessarily appropriate for the request; do not label it as missed work
without checking its relevance and dependencies.
The metrics API may expose at most 256 completed, relative stage spans, with a
dropped-span count. Keep spans limited to allowlisted stage names and monotonic
times; do not attach prompt or tool contents. Aggregate totals remain available.
When System 1 finishes after observed tools, a foreground Main call receives
a bounded continuation note listing validated tool names and masked result
excerpts only for actions whose policy permits sharing results with the
decision backend. Agent Zero may omit earlier tool records from the active
model prompt. The note marks excerpts as untrusted data, points Main to host
history for verification, and asks it to finish without repeating a recorded
call unless necessary. It is not added to background advisory calls or later
user turns, and never copies request text, tool arguments, or credentials.
The read-only metrics API exposes per-agent Utility bypass and fallback counts
and timing, without prompts, responses, or credentials. Original-Utility
model-call timing is grouped into allowlisted memory-query, memory-filter,
memory-ingestion, and other categories; never expose call text through those
metrics. Filter eligibility counters may expose only allowlisted reason names
and counts, never candidates or request text. Plugin-owned timing
hooks bracket host prompt preparation, foreground/background Main calls, tool
execution, and the memory-recall hook span. Delayed recall may outlive that span;
ingestion is deferred by the host at monologue end, so this hook layer does not
measure its background index writes. Spans may
overlap; never add them to infer wall time. Incomplete spans are omitted.
Utility bypasses only
verified host memory-query and bounded candidate-filter prompt shapes; it
returns validated query text or JSON indices in the normal Utility callback.
Candidate text is never truncated for a decision: a verified candidate may be
up to 4000 characters, but the complete encoded state and finite choices must
still fit the configured decision payload limit or the original Utility call runs.
Candidates may be
compared against the complete validated current-user envelope even when that
request exceeds the direct-query word limit. Only candidate filtering uses this
separate validation; query preparation retains its short direct-query rules.
Unknown envelope fields, attachments, system messages, malformed requests, and
oversized complete payloads fall back without truncated comparison.
Filter subset choices use exact JSON index lists as compact descriptions, with
one global format instruction and the full pinned host relevance contract once.
Choice IDs and response mapping remain stable;
the complete request, history, candidates, limits, and confidence gate are unchanged.
Unknown shapes, errors, and generative work use the original Utility model.
The query fast path accepts first-turn history only when its isolated `user:`
envelope decodes to the same sanitized current-user fields as the `user:`
request, optionally after the one pinned host bootstrap record. It rejects
prior, other AI, tool, or truncated history. Query and filter system templates are matched
by pinned normalized text, not broad prompt similarity.
Configured fixed Utility routes are separate and must reject every recognized
built-in `_memory` system prompt, including ingestion and summary templates.
Embedding-only mode may add a bounded Decider-selected provenance reminder to a
recognized memory query, filter, or ingestion Utility request, then always leaves
the selected Utility model, embedding vectors, memory index, and host write path
in control.
`independent_while_main` action opt-in is required before System 1 may continue
dispatching a configured action while a background Main correction is pending;
the host remains the sole executor. Background advice may guide only a later
decision, after rechecking the request and action configuration. If the model
call outlives the advisory deadline, detach its result and never apply it later.
Allow at most one unfinished detached advisory per agent so repeated turns do
not accumulate provider calls; subsequent uncertainty falls back to Main.
`parallel_safe` is a separate per-action opt-in for native parallel batching.
Only explicitly independent calls may be batched, with each child result
validated and counted by native job ID. Dependent actions require terminal
host-recorded prerequisite results. Native
`wait: false` lets foreground Main use its ordinary model and tools while
already-submitted System 1 jobs run, including a single opted-in child. This
kickoff requires the pinned, reviewed native dispatcher source contract;
changed or overridden host sources fall back to sequential routing. Recheck
that contract at submission, and honor `parallel_wait_for_results: true`.
The reviewed direct-worker contract covers only the parent context's exact
agent0/config identity; other agents or profile/config overrides use normal
sequential submission. Check the parent's native tool policy for every child
again at submission. Exclude dispatcher-forbidden tools, method-style native
names and subordinate-agent calls from this direct-tool overlap path.
It does not start a second Main agent loop or let a plugin task call the
parent's `process_tools` concurrently. Later independent work must be submitted
at a host loop boundary or explicitly delegated by Main.
The response tool must be guarded
until every outstanding job has a host-recorded terminal result, including
partial or reordered collections. Never treat a started job as observed
evidence. Classify each child's recorded result as well as its native job
state; error text is never shared or bound as successful evidence.
Malformed or missing start receipts retain an unresolved submission and its
call-signature reservations; finalization must check that state even when no
job IDs were parsed. A reviewed native registry may recover exact IDs using
the pre-submission registry baseline, parent agent, child index and canonical
call signature, but never supplies result content as evidence. In that reviewed
dispatcher, registry absence proves a child is no longer in flight; record it
as unavailable without result content or automatic retry. Unknown baselines,
changed hosts and ambiguous mappings keep finalization blocked. Native await
timeouts do not cancel jobs. Collection or cancellation needs actual native
IDs; the host includes its running/ready job list in Main's prompt.
Main-owned native parallel child signatures enter the same per-task replay ledger by
validated job ID. Pending and successful calls block a matching System 1
submission, while a verified failed child may be retried. Unparsed job
results remain blocked. The foreground `system1_delegate` tool returns a bounded eligible
choice to System 1 in the same monologue; the runtime checks the current
request, config, action cap, permissions, and canonical call ledger again.
Delegated decisions retain a Main fallback so System 1 can decline; the
Decider sees bounded handback context. A declined action is not completed
evidence. Do not accept an identical delegation again without a new host
observation, and tell Main explicitly when no delegated action ran.
Keep its `prompts/agent.system.tool.system1_delegate.md` entry installed so
Main sees the exact native tool name and `action_ids` argument shape.
The guarded
`set_messages_after_loop` WebUI extension recognizes its `system1-main-` ID
and marks only that record with an S1
badge and accent. It must tolerate virtualized entries with no DOM element and
leave native Gen, Tool, and other Info records unchanged.
The `message_loop_end` hook closes a pending step if an interruption bypasses
the decision hook. Logging failures must not change model routing.
The model editor keeps the three System One Mode toggles in their native model
sections and injects a shared Decider Model section beside them. It uses native
field and search styles, but saves Decider through plugin config because the
host preset serializer owns only native model slots. The plugin adds a
read-only Decider identity row in the native preset overview, using the same
row styles as Main, Utility, and Embedding. It must reflect the global shared
connection across preset changes, tolerate missing settings/store, and avoid
adding Decider to the host preset serializer. The get hook supplies a
read-time migration for matching legacy connections. A conflict among enabled
legacy connections requires the user to select one in the Decider editor; do
not silently choose. Preserve legacy values and unrelated plugin keys. Once a
shared Decider is selected, never inherit a stale per-role endpoint or credential.
The host's direct config-read API needs the same migration as runtime hooks.
The Utility before-call hook may replace the model with a guarded fixed-response
wrapper only for an exact configured system/message pair and a high-confidence
finite decision. Preserve the original Utility model for every fallback and
the host callback contract. Utility metrics count all hook calls, decisions,
bypasses, and fallback attempts per agent and contain no
request or response text. The save hook validates route uniqueness, bounds,
and response choices, and removes the UI draft. Route prompts and fixed response
choices are sent to the configured decision backend only for an exact match;
recognized built-in `_memory` prompts are always ineligible for fixed responses.
Oversized choices fall back to Utility. A decided fallback must not issue a
second decision before the original Utility call.
The plugin settings view parses Action eligibility and Utility fixed responses
through Alpine methods on input and blur. It guards the host Save action until
both JSON drafts are valid, displays inline errors, and restores the host Save
method when the view is removed. Because the current host plugin modal does not
trap keyboard focus, this view focuses its first control on open, keeps Tab and
Shift+Tab within the modal, and removes its listener on close. Do not alter
background plugin-list controls or host modal behavior globally.

Foreground `system1_delegate` accepts optional `goal` guidance: a nonblank
single-line string of at most 1000 characters, masked with the host secrets
manager before retention in System 1 state or sharing with Decider. Invalid scope or unavailable
masking rejects delegation without truncation. IDs-only calls remain compatible.
The goal is not evidence or authorization and cannot alter original task identity,
argument bindings, permissions, prerequisites, or the host observation ledger.
Delegation replay checks ignore goal changes. Never serialize the goal in S1
timeline events; include it only as quoted guidance in delegated decision context.
Delegated context starts with the bounded decision rule, current quoted goal and
IDs, then the full original request labeled as broader context and constraints,
host observations, and any Main correction. Main owns the remainder of the task;
Decider may still decline irrelevant choices. Fail closed on complete-context
size limits instead of truncating any section.
