# Agent Plugins DOX

This repository uses DOX: a hierarchy of `AGENTS.md` files that agents must read before editing and keep current after meaningful changes.

## Purpose

This repo is the Omni-NexusAI Agent Plugins monorepo. It holds existing Agent Zero and Agentspine packages plus a separate source area for future plugins shared across agent frameworks. It is separate from a local runtime checkout; some existing packages originated from container snapshots.

## Ownership

- `plugins/` contains installable Agent Zero-style packages and retained historical sources.
- `portable/` contains future multi-framework plugin sources; it is not an installable package directory.
- `catalog.json` records source paths, framework compatibility, status, and verified distribution repositories.
- `sync-to-repos.sh` previews cataloged packages and publishes only an explicitly selected active package to an existing standalone repository through a pull request.
- `CONTAINER_SYNC.md` records source provenance and compatibility boundaries for existing packages.
- Each plugin owns its manifest, README, extension hooks, helper code, assets, and nearest `AGENTS.md`.
- Runtime logs, installed settings, bytecode caches, and container filesystem snapshots are not source artifacts.

## Local Contracts

- Read this file first, then read every child `AGENTS.md` on the path to files you will edit.
- The closest `AGENTS.md` controls local details; parent docs still control broader workflow and safety rules.
- Keep manifests, README files, DOX files, and implementation behavior aligned.
- Preserve installed plugin directory names when they are used in manifests or Python import paths.
- Include shared portable code inside each assembled platform distribution; do not depend on this monorepo at runtime.
- Never release a historical source or an unassembled portable source tree.
- When comparing to Agentspine or a baked A0 runtime, clearly state which container, image, branch, or commit is the source of truth.
- Update the nearest owning `AGENTS.md` when behavior, structure, config contracts, UI contracts, verification requirements, or sync status change.

## Work Guidance

- Prefer plugin-local code over host-runtime edits.
- Keep runtime patches idempotent and guarded.
- Preserve unknown config keys when reading or writing host/plugin settings.
- Avoid generated files such as `.pyc`, `__pycache__`, build output, logs, or local secrets.
- Keep container-synced plugins faithful to their declared snapshot unless intentionally upgrading them.

## Verification

- For Python changes, parse or compile touched Python files when practical.
- For WebUI changes, inspect the affected DOM/CSS behavior and verify safe degradation when the target store/page is absent.
- For sync work, compare plugin manifests and source files against the declared runtime snapshot.
- Verify catalog paths, release eligibility, and preview behavior before publication.

## Child DOX Index

- `plugins/AGENTS.md`: shared plugin packaging, portability, container sync, and per-plugin guidance.
- `portable/AGENTS.md`: shared core, framework adapters, and platform packaging rules for future portable plugins.
