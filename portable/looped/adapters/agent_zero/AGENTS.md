# Looped Mode (Agent Zero package) DOX

This folder is assembled from `portable/looped/` in the Agent Plugins monorepo.
Edit the portable source and re-run `assemble.py`; do not edit this copy.

## Ownership

- `plugin.yaml`, `default_config.yaml`: identity and defaults.
- `helpers/looped_core/`: the framework-independent core (copied in).
- `helpers/runtime.py`: host glue for every hook; `helpers/command.py`: the
  `/looped` command parser.
- `extensions/python/`: hook files. Each is a thin call into `helpers/runtime`.
- `extensions/webui/`: composer control and composer-side `/looped` handling.
- `commands/`: `/looped` entry for hosts with the built-in command catalog.
- `api/`: per-chat mode and metrics handlers.
- `webui/config.html`: settings page.

## Contracts

- Hooks import the package as `usr.plugins.looped`, falling back to
  `plugins.looped`.
- Hook files stay thin; behaviour belongs in `helpers/` where it is tested.
- A hook must never raise into the agent loop.
- See the monorepo's `portable/looped/AGENTS.md` for the full contract list.
