# Portable Sources DOX

## Purpose

`portable/` owns source for plugins shared across agent frameworks.
Convo and System 1 are planned. A2A Format Unifier has a framework-independent
core and Agent Zero adapter; its assembled package lives in `plugins/`.

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

## Child DOX

- `a2a_format_unifier/AGENTS.md`: known JSON-RPC profiles, context persistence,
  ASGI conversion, native Agent Zero binding, assembly and verification ownership.
