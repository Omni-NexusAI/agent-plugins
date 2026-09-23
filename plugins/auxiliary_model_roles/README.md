# Auxiliary Model Roles

This Agent Zero plugin adds optional Tool and Coding specialists under Main.
Both are disabled until configured. The native provider credentials remain
authoritative; enter a provider, model name, and optional API base. The models
can be hosted or local through Agent Zero's existing provider support.

Main delegates a bounded goal through `auxiliary_delegate`. Tool may submit
one strict JSON action to Agent Zero's native executor, which applies its
normal permission and history path. It then returns the outcome or an
escalation to Main. Coding returns code or findings to Main. Neither
specialist silently takes over the Utility model or creates a Computer model
category. Turning a role off prevents new delegation immediately; an in-flight
model request completes or reaches its timeout.

The plugin works by itself. If System 1 is installed and enabled, the two
plugins can select a specialist through the same host delegation tool. Main
System 1 is the default first decision point; its plugin settings can choose
Tool first. System 1's action eligibility still gates its direct fixed actions.
