# Portable plugin sources

This directory is reserved for plugins that can support more than one agent
framework. Convo and System 1 are planned here; no plugin implementations or
installable packages have been added yet.

Each future plugin uses `portable/<plugin>/core/` for framework-independent
logic and `portable/<plugin>/adapters/<framework>/` for host integration.
An adapter owns host hooks, settings, tool dispatch, and packaging for its
framework. A published distribution must contain its required core code and
run without access to this monorepo.

Portable source folders are not installable Agent Zero packages. Platform
exporters and their exact output layouts will be added when the first portable
plugin is implemented. Existing packages remain in [`plugins/`](../plugins/).
