# Portable Sources DOX

## Purpose

`portable/` owns source for future plugins shared across agent frameworks.
Looped Mode has a portable core and an Agent Zero adapter. Convo and System 1
are planned; no placeholder plugins are kept.

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

- `looped/AGENTS.md`: looped-mode strategies, Agent Zero adapter, isolated test
  project, benchmark, and independent assembly.
