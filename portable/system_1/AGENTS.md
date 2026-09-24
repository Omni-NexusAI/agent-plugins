# System 1 DOX

## Ownership

- `core/` owns finite-choice decisions, backend clients, validation, and policy.
- `adapters/agent_zero/` owns Agent Zero hooks, settings UI, and assembly.
- `../../plugins/system_1/` is the assembled Agent Zero distribution; regenerate it with `assemble.py`.

## Contracts

- The assembled package must run without this source tree.
- Only the host may execute actions. Decisions select predeclared actions with exact arguments.
- A backend failure escalates to the existing model and never switches providers silently.
- OpenRouter Jev uses the Decisions API and its shared Agent Zero provider key.
  Native chat providers may route, but their self-reported confidence never
  authorizes direct fixed action dispatch.
- Embedding vectors remain the host embedding model's output.
- Keep memory and monitoring work bounded. No background task may mutate agent state directly.
- On the current Agent Zero host, the first model turn is loop iteration zero;
  fast actions may run there once, then later iterations belong to the host.
- The Agent Zero adapter records a single native Info step with a `system1-main-`
  ID for an enabled
  Main decision, before the native GEN step. It updates the same record with
  route, backend, confidence when available, and elapsed time. Never put
  request text, tool arguments, or credentials in the timeline record.

## Verification

- Run the core tests, assembly check, and package import smoke test outside the monorepo.
- Exercise the rendered Agent Zero settings and plugin page before calling this ready for review.
