# Portable plugin sources

This directory holds sources intended for more than one agent framework.
[`system_1/`](system_1/) has a portable decision core and an Agent Zero adapter.
Convo remains planned and is outside the current plugin work.

Each future plugin uses `portable/<plugin>/core/` for framework-independent
logic and `portable/<plugin>/adapters/<framework>/` for host integration.
An adapter owns host hooks, settings, tool dispatch, and packaging for its
framework. A published distribution must contain its required core code and
run without access to this monorepo.

Portable source folders are not installable Agent Zero packages. Run
`python portable/system_1/assemble.py` from the repository root to create
[`plugins/system_1/`](../plugins/system_1/). The exporter copies all adapter
files and the shared core into that independent package. Use `--check` to
verify the copy before review. Existing packages remain in [`plugins/`](../plugins/).
