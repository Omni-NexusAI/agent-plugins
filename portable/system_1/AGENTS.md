# System 1 DOX

## Ownership

- `core/` owns finite-choice decisions, backend clients, validation, and policy.
- `adapters/agent_zero/` owns Agent Zero hooks, settings UI, and assembly.
- `../../plugins/system_1/` is the assembled Agent Zero distribution; regenerate it with `assemble.py`.
- `VERIFICATION.md` records sanitized local behavior evidence and open acceptance gates.

## Contracts

- The assembled package must run without this source tree.
- Only the host may execute actions. Decisions select predeclared actions with
  fixed or typed, bounded argument bindings from a validated request or a complete,
  masked prior JSON result. A second System 1 decision is eligible only after the host
  records the selected tool's result in the same monologue. Per-turn state must
  reset on a new monologue, cap actions, and avoid replaying a used action ID.
- Tool results are not sent to a decision backend by default. An action must
  explicitly opt into bounded result sharing. Returning the observed result
  directly to the user is a separate explicit per-action opt-in; otherwise
  open-ended output goes to Main. Mask tool results with the host secrets
  manager before retaining them, fail closed if masking fails, and recheck the
  action definition and sharing flags before any subsequent backend call.
- A backend failure escalates to the existing model and never switches providers silently.
- OpenRouter Jev uses the Decisions API and its shared Agent Zero provider key.
  Native chat providers may route, but their self-reported confidence never
  authorizes direct fixed action dispatch.
- One Decider connection supplies every enabled Main, Utility, and Embedding
  System One Mode. Keep those role toggles independent. Migrate matching legacy
  per-role connections without discarding them; conflicting enabled connections
  require an explicit shared choice. Bound complete request state using the
  configured Decider context window while reserving room for choices and output.
  Reject oversized state rather than dropping a correction, tool result, or
  Utility message.
- Embedding vectors remain the host embedding model's output.
- Utility memory query and relevance decisions require verified Agent Zero prompt
  shapes and validated outputs. Unknown, oversized, malformed, uncertain, or failed
  decisions fall back to the full original Utility model call. Utility still writes
  memory entries, summaries, titles, and other open-ended text. Per-agent metrics
  count bypassed calls, ordinary generation, fallback calls, and decision/model time
  without storing prompt contents or credentials. Fixed routes must reject every
  recognized built-in `_memory` system prompt, including query, filtering, summary,
  extraction, consolidation, and history prompts. The direct query/filter paths
  require their current exact normalized templates. A direct query may accept the
  initial `user:` history entry only when its decoded sanitized current-user
  fields equal the `user:` request envelope. It also accepts one pinned host
  bootstrap AI record followed by that entry and at most the host's one verified
  trailing line feed. Prior entries, other AI output,
  tool records, or a changed memory-like host template are conservatively kept
  on the original Utility path. Embedding-only mode may append
  bounded provenance guidance to recognized memory query, filtering, or ingestion
  calls after direct-response eligibility is complete; it never changes the host
  embedding model, vectors, index, or write operation.
- Stage metrics bracket verified host hook points for prompt preparation,
  foreground/background Main calls, tool execution, and the memory-recall hook
  span. They retain only counts and elapsed time. Delayed recall can continue
  after that span; the host schedules ingestion in a background thread, so the
  hook boundary does not time index writes. Overlapping
  spans are reported separately and must not be summed as wall time.
- Utility fixed responses require an explicit exact system/message route and a
  predeclared finite response. A guarded model wrapper must preserve the host
  Utility call and callback shape, recheck the request and route at call time,
  and fall back to the original Utility model on uncertainty or errors.
  Generative Utility requests are ineligible. Count all hook calls, decisions, bypasses,
  fallbacks, and timing without retaining prompts or credentials. Bound the
  complete decision payload, including fixed response choices, and avoid a
  second decision call after a route has already fallen back.
- Keep memory and monitoring work bounded. No background task may mutate agent state directly.
- Main correction begins only for an uncertain subtask. While it is pending,
  System 1 may dispatch only explicitly opted-in independent actions through
  the host. Recheck the request and configuration before accepting later advice;
  stale advice must not commit an action or overwrite a newer result. An advisory
  deadline must return even if its underlying model call ignores cancellation.
  Retain at most one such unfinished advisory call per agent; skip new advice
  until it exits, and never apply a late result.
- Main may return a bounded eligible action or delegate a finite choice to
  System 1 in the same monologue. Revalidate the task, configured action,
  resolved arguments, permissions, and prior call ledger at the point of
  submission. Main retains open-ended reasoning and final prose. A foreground
  Main delegation uses the plugin tool; it must not bypass the host tool path.
  System 1 may decline a delegated choice. Do not present that handback as a
  completed action or accept an identical handback again without new host
  evidence.
- Use Agent Zero's native `parallel` tool only for calls independently marked
  both `independent_while_main` and `parallel_safe`. The first flag covers
  concurrency with Main; the second asserts the calls do not depend on each
  other or share mutable state. Track each native job ID and terminal result
  separately, including reordered or partial collections. A started job is
  not evidence of completion, and Main may not finish with uncollected jobs.
  Dependent calls wait for their prerequisite host-recorded results.
- Prevent automatic replay across different configured action IDs and after
  a successful Main call by comparing canonical tool name and resolved
  arguments; retain only a hash of the canonical call in task state. Main's
  native parallel children also enter that ledger by validated job ID: a
  pending child blocks replay, terminal success stays blocked, and a verified
  failed child may be retried. Unparsed or mismatched job results fail closed.
  A native child whose recorded result is an error is failed evidence even if
  the native parallel envelope labels the job successful.
- On Agent Zero, the first model turn is loop iteration zero. A later
  iteration can make another System 1 decision only after an observed result
  from its pending tool, within the action cap; other iterations belong to Main.
- The Agent Zero adapter records a native Info step with a `system1-main-`
  ID for each eligible Main decision, before the native GEN step. It updates each record with
  route, backend, confidence when available, and elapsed time. Never put
  request text, tool arguments, or credentials in the timeline record. Name a
  selected host tool and, on handoff, distinguish a proposed tool from one
  that actually ran; display `None` when there was no proposed tool. Mark
  failed host actions as failures, not available observations.

## Verification

- Run the core tests, assembly check, and package import smoke test outside the monorepo.
- Exercise the rendered Agent Zero settings and plugin page before calling this ready for review.
