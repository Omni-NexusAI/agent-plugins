# System 1 DOX

## Ownership

- `core/` owns finite-choice decisions, backend clients, validation, and policy.
- `adapters/agent_zero/` owns Agent Zero hooks, settings UI, and assembly.
- `../../plugins/system_1/` is the assembled Agent Zero distribution; regenerate it with `assemble.py`.

## Contracts

- The assembled package must run without this source tree.
- Only the host may execute actions. Decisions select predeclared actions with exact,
  nonempty arguments. A second System 1 decision is eligible only after the host
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
- On Agent Zero, the first model turn is loop iteration zero. A later
  iteration can make another System 1 decision only after an observed result
  from its pending tool, within the action cap; other iterations belong to Main.
- The Agent Zero adapter records a native Info step with a `system1-main-`
  ID for each eligible Main decision, before the native GEN step. It updates each record with
  route, backend, confidence when available, and elapsed time. Never put
  request text, tool arguments, or credentials in the timeline record.

## Verification

- Run the core tests, assembly check, and package import smoke test outside the monorepo.
- Exercise the rendered Agent Zero settings and plugin page before calling this ready for review.
