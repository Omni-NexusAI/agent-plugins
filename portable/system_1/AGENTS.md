# System 1 DOX

## Ownership

- `core/` owns finite-choice decisions, backend clients, validation, and policy.
- `adapters/agent_zero/` owns Agent Zero hooks, settings UI, and assembly.
- `../../plugins/system_1/` is the assembled Agent Zero distribution; regenerate it with `assemble.py`.

## Contracts

- The assembled package must run without this source tree.
- Only the host may execute actions. Decisions select predeclared actions with exact arguments.
- A backend failure escalates to the existing model and never switches providers silently.
- Embedding vectors remain the host embedding model's output.
- Keep memory and monitoring work bounded. No background task may mutate agent state directly.

## Verification

- Run the core tests, assembly check, and package import smoke test outside the monorepo.
- Exercise the rendered Agent Zero settings and plugin page before calling this ready for review.
