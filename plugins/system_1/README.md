# System 1 for Agent Zero

This plugin adds finite-choice routing in front of Agent Zero's Main model.
It supports TypeSafe Jev directly, Jev through OpenRouter's Decisions API,
the `parallel-decision` llama.cpp fork's `POST /v1/decision`, and the host's
standard chat providers for bounded routing. Configure existing services; installation never
downloads a model or starts a server. The standard llama.cpp server does not
provide this decision endpoint.

The plugin is disabled by default. Configure the shared **Decider Model** beside
Agent Zero's model sections, then enable **System One Mode** independently in
Main, Utility, or Embedding. Decider holds the provider, model name, endpoint,
credential, and context window for all enabled modes. The toggles decide where
Agent Zero uses that shared decision service. Decider settings save through the
plugin and apply across model presets; they do not change the selected Main,
Utility, or Embedding models. The model preset overview shows the configured
Decider beside those three model identities, even though its connection is global.
When Main mode is enabled, each eligible decision appears as an expandable **S1**
step in the chat process timeline. It shows whether System 1 selected an
eligible action, delegated to a specialist, or handed off to Main, plus backend,
elapsed time, and confidence when available. Native Gen and Tool steps remain
unchanged. For a selected action, S1 names the tool submitted to Agent Zero;
the native Tool step shows its actual execution and result. The S1 detail
also names a proposed tool when confidence or a changed task prevents its
execution. A handoff with no proposed tool says `None`, so the record does not
imply that a call ran. It intentionally omits request text and tool arguments.
If System 1 chooses to await Main despite policy-eligible independent choices,
the timeline records the number of offered alternatives and the time spent
waiting. Eligibility does not establish that an alternative was relevant to
the user's task.
The per-chat metrics API also exposes a bounded list of completed stage spans
with times relative to that chat's first measured stage. This permits overlap
analysis across Main foreground/background, prompt preparation, tool execution,
and memory recall without storing requests, arguments, or credentials. Native
parallel child timing is still read from the host's own tool records.
These mode toggles are global across model presets and agent profiles. Existing
per-section connections migrate to Decider on read when they agree among
enabled modes. If enabled modes have different saved connections, choose the
shared Decider in the model editor; the old values remain for rollback until
you change them. The context window limits each complete decision request while
reserving room for choices and a response. An oversized request escalates without
truncating observations, corrections, or Utility text. It does not alter Main or
Utility context size.
For hosted Jev, set the configured environment variable (default
`SYSTEM_1_JEV_API_KEY`) through Agent Zero's environment settings. OpenRouter
uses Agent Zero's shared OpenRouter key and its Decisions API; the model
`typesafe/jev-latest` is mapped to OpenRouter's `~typesafe/jev-latest` alias.
Other native chat providers use Agent Zero's model configuration and credentials
for routing, but their self-reported confidence is not trusted for direct fixed
action dispatch. A local
decision endpoint needs no key unless your server requires one.

Main can choose only from `policy.actions` and the Main fallback. Each action
declares a fixed `tool_name` and fixed arguments or typed, bounded
`argument_bindings`. Bindings may extract an unambiguous request field or a
validated field from a complete, masked JSON result of a prior opted-in action.
The decision model cannot generate arbitrary arguments. Agent Zero still validates and executes the chosen tool
under its usual permissions and history. After a nonterminating action, the
plugin waits for the host to record that tool's result before requesting another
finite decision. The action count is bounded by `max_actions_per_turn` (default
three, maximum eight), and an action ID cannot repeat within a turn. A tool
error or missing result goes to Main. A raw MCP result never finishes a user
request: Main receives recorded evidence and writes a useful final answer
when prose is needed, without repeating a successful call unless evidence is
insufficient. The continuation note carries only bounded, masked result
excerpts from actions that allow backend sharing; the full host Tool history
remains authoritative. Empty or uncertain choices, service
errors, and open-ended work also go to Main. With an empty action map, System 1
has no direct actions to dispatch. If Auxiliary Model Roles is installed and
configured, System 1 may delegate a Tool or Coding goal through Agent Zero's
normal `auxiliary_delegate` tool. The specialist result returns to Main.

Utility can also bypass a model call for two verified Agent Zero memory call
shapes: an unambiguous current request can become the search query, and a
small enumerated candidate list can receive a validated JSON list of relevant
indices. Unknown or changed shapes, malformed or oversized candidates,
low-confidence or failed decisions use the complete original Utility call.
At an initial recall, Agent Zero has already stored the current message in
history; the query fast path accepts it only when the isolated `user:` history
envelope decodes to the same sanitized current-user fields as the `user:`
request, optionally after the one pinned host bootstrap greeting. Any prior,
other AI, or tool history uses Utility. Both system prompts are pinned by normalized template content, so a
host template revision also uses Utility until reviewed.
Memory ingestion, summaries, chat titles, and other generated text remain with
the Utility model. The selected embedding model still creates vectors, and
the existing memory index is preserved. With only Embedding System One Mode
enabled, the Decider can add a bounded provenance reminder to recognized memory
query, filtering, or ingestion calls before Utility runs. It never replaces the
selected Utility or embedding model, vectors, index, or memory write.

Separately, an optional fixed route can bypass a non-memory Utility call only
for an explicitly configured exact system and message pair with predeclared
response choices. The finite backend chooses
one response or `ordinary`; a confidence below the policy threshold, a changed
request or configuration, and any backend error use the original Utility model.
Chat backends cannot authorize fixed responses. Each response is limited to
4000 characters, and the normal Utility callback receives the selected text.
The exact system instruction, message, and configured response choices are sent
to the chosen decision backend; configure these routes only with content that
backend may receive. The combined decision payload is bounded by
`max_state_chars`, and oversized routes use the original Utility model.
The adapter keeps per-agent bypass, fallback, and ordinary-generation counts
and separate Decider and Utility timing without retaining prompts or secrets.
The read-only per-chat plugin metrics endpoint exposes these counts for
practical comparisons. Count avoided Utility calls as `bypassed` divided by
completed Utility calls (`bypassed + ordinary_generations + fallback_model_calls`).
In-flight calls are excluded from that denominator.
The endpoint also groups measured original-Utility model calls into
`memory_query`, `memory_filter`, `memory_ingestion`, and `other`, reporting
counts and elapsed seconds without request text. These groups identify model
time, not embedding search or index-write time.
The `memory_filter_gate` counters also separate an unsupported host shape,
oversized decision payload, attempted choice, fallback, and installed bypass.
They include fixed rejection reason counts without candidate text and help
explain why a filter still used Utility. Verified candidates up to 4000
characters are considered without truncation; the complete encoded decision
must fit `max_state_chars`, or the original Utility call runs.
The endpoint also reports count and elapsed seconds at the host's prompt
preparation, foreground/background Main, tool execution, and memory recall hook
boundaries. Delayed recall can continue after its hook span. Ingestion runs in
a host background thread and its index-write time is not measured by these
hooks. The measured spans can overlap during Main advice;
compare them separately and use measured prompt-to-final-answer wall time for
the full task.

For example, a known Utility caller with exact prompt text can opt into two
fixed outputs:

```yaml
utility:
  fixed_routes:
    - system: "Classify this exact request as yes or no."
      message: "Is this item ready?"
      responses:
        yes: "yes"
        no: "no"
```

Match against the text after Agent Zero's secret masking hook. Do not configure
fixed outputs for summaries, query generation, memory ingestion, or other work
that needs generated content. The adapter rejects a fixed route for every
recognized built-in `_memory` prompt, including query, filtering, summaries,
extraction, consolidation, and history prompts, even if it exactly matches a
configured route. Query and filter bypasses require their current exact
normalized host templates; a changed but memory-shaped template is kept on the
original Utility path. The plugin page has Fast, Balanced, and Conservative starting
presets plus adjustable thresholds and bounded monitoring limits.
The first monitor observes native user interventions while Main works and asks
the host loop to process high-priority ones; it stops after its configured time
or check limit. Other event sources require a future host adapter.

## Configured action example

```yaml
policy:
  actions:
    recall_project_context:
      description: Recall stored context about the current project.
      tool_name: memory_load
      tool_args:
        query: current project
        limit: 3
      share_result_with_backend: true
      return_result_to_user: false
      independent_while_main: false
      parallel_safe: false
```

`share_result_with_backend` sends at most `max_result_chars` (default 2000)
of the observed result to the next decision. It is false by default.
`return_result_to_user` separately permits System 1 to choose a fixed finish
route that returns the observed result without rewriting it. Use it only for
tools whose complete result is suitable for display; truncated results cannot
take that finish route. The two permissions are independent.

`independent_while_main` is a separate per-action opt-in for a fixed action
that remains valid while Main reasons about an uncertain subtask. Leave it
false for actions that depend on Main's pending answer, may change the same
state Main is reviewing, or could produce a duplicate effect. System 1 submits
an opted-in action through the normal host tool path; Main's later advice is
applied only to subsequent decisions. A changed request or action definition
invalidates the pending choice. A timed-out Main advisory does not delay later
System 1 decisions or apply a late correction.

Main may select a configured action itself or hand a bounded set of eligible
action IDs back to System 1 through `system1_delegate`. The plugin checks the
current request, action definitions, permissions, and prior calls again before
dispatch. System 1 can decline a handback if the action is unsafe or uncertain;
Main then sees that the action did not run. The same handback cannot repeat
without new host evidence. Main can still use ordinary Agent Zero tools for open-ended work and
writes the final answer from recorded evidence. The plugin's native tool prompt
lists the exact `action_ids` argument shape for Main.

`parallel_safe` is another separate per-action opt-in. Set it to true only when
the action can run beside other opted-in actions without depending on their
results or changing shared state. System 1 may then submit one or more selected
actions through Agent Zero's native `parallel` tool with `wait: false`, allowing
foreground Main to reason and use its ordinary coding tools while those jobs
run. This does not require a background Main advisory call. Async kickoff is
enabled only for the reviewed, pinned native dispatcher sources; changed or
overridden host sources conservatively use sequential routing. Set
`parallel_wait_for_results: true` to collect the batch before Main continues.
The reviewed worker cloning contract covers the parent context's exact root
agent and config only; other agents and config/profile overrides stay on the
normal single-action host path. System 1 checks each child's parent-scoped tool
permission again at submission. `document_query`, `response`, `parallel`,
method-style native tool names and subordinate-agent calls are ineligible for
this direct-tool overlap path.
This is bounded retrieval overlap: it does not create an autonomous second
Main loop or initiate new host tools from a plugin background task. Each child has its own
job ID and recorded outcome; a started job is not a completed result. Dependent
actions wait for their prerequisites, and the plugin defers a final answer
until every outstanding native job is collected. The same resolved tool call
cannot be automatically replayed under another configured action ID. Main's
own native parallel children also enter the task's call ledger: pending or
successful children block a matching System 1 call, and only a verified
failed child permits retry. A child result carrying an error is not shared as
successful evidence even when the native job envelope reports success.

A missing or malformed start receipt keeps the submission unresolved and
blocks finalization even if no job ID was parsed. When the reviewed dispatcher
registry is available, System 1 may recover exact IDs from its pre-dispatch
baseline and matching owner, index and canonical call signatures. It does not
copy registry results as evidence; results still need a normal host collection.
A registry-proven absent child is recorded as unavailable, with no result and
no automatic retry. Unknown or ambiguous mappings remain blocked. Main sees
the native running/ready job list in its prompt and can collect real IDs with
`parallel` arguments `{"action":"await","job_ids":["actual-id"]}` or cancel
them with `{"action":"cancel","job_ids":["actual-id"]}`. Awaiting can time out
while jobs keep running; only recorded terminal results clear the normal guard.

Only configure actions whose exact tool schema and permissions you have
verified on the installed Agent Zero version. There is no automatic local to
hosted fallback.

For dynamic arguments, `argument_bindings` can supplement fixed `tool_args`.
Each binding names a `source` (`request` or `result`), a supported `value_type`,
and bounded extraction rules. A result binding names `from_action` and a JSON
`path`; the source action must set `allow_result_bindings: true`. The plugin
rejects unknown types, malformed values, incomplete results, and changed
source definitions. Keep action IDs distinct and configure only fields whose
host tool schema has been verified.
