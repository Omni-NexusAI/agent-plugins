# Portable plugin sources

This directory holds shared plugin sources and framework adapters.
[A2A Format Unifier](a2a_format_unifier/) is implemented with an Agent Zero
adapter and a self-contained distribution in `plugins/a2a_format_unifier`.
Convo and System 1 remain planned.

Each plugin uses `portable/<plugin>/core/` for framework-independent
logic and `portable/<plugin>/adapters/<framework>/` for host integration.
An adapter owns host hooks, settings, tool dispatch, and packaging for its
framework. A published distribution must contain its required core code and
run without access to this monorepo.

Portable source folders are not installable Agent Zero packages. Each plugin
documents its assembly command and output layout. Installable packages remain
in [`plugins/`](../plugins/).
