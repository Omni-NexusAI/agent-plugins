# Portable Sources DOX

## Purpose

`portable/` owns source intended to be shared across agent frameworks.
System 1 has a portable core and an Agent Zero adapter. Convo remains planned.

## Local Contracts

- Put framework-independent decisions and data contracts in each plugin's `core/`.
- Put host hooks, tool dispatch, settings, and distribution assembly in
  `adapters/<framework>/`.
- Keep every assembled platform package self-contained at installation time.
  Do not import code from a sibling source directory or the monorepo root.
- Do not mark source here as an installable package or release it directly.
- Add a child `AGENTS.md` when a real portable plugin is introduced, and record
  its supported frameworks and packaging verification there.

## Verification

- For each future adapter, test its assembled output outside this checkout.
- Keep the repository catalog, README, and adapter documentation aligned.

## Child DOX Index

- `system_1/AGENTS.md`: finite-choice backends, Agent Zero adapter, and independent assembly.
