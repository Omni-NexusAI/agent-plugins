# Auxiliary Model Roles DOX

This package owns optional Tool and Coding model roles for Agent Zero. Its
config, UI, delegation tool, and model helper stay within this folder.

Main owns delegation. The specialist returns a result through the normal tool
history; it does not directly execute arbitrary host tools. Every call reads
current enablement so disabling a role takes effect on the next dispatch.
The plugin can run without System 1. When System 1 is installed, its optional
finite-choice route may invoke the same delegation tool through the host.

Verify both rendered UI states and live host permissions before review-ready.
