# Auxiliary Model Roles

This Agent Zero plugin adds optional Tool and Coding specialists under Main.
Both are disabled until configured. The native provider credentials remain
authoritative; enter a provider, model name, and optional API base. The models
can be hosted or local through Agent Zero's existing provider support.

Main delegates a bounded goal through `auxiliary_delegate`. Tool returns
proposed actions and observations to Main, which uses the normal Agent Zero
tool path for any action. Coding returns code or findings to Main. Neither
specialist silently takes over the Utility model or creates a Computer model
category. Turning a role off prevents new delegation immediately; an in-flight
model request completes or reaches its timeout.

The plugin works by itself. If System 1 is installed and enabled, the two
plugins can select a specialist through the same host delegation tool. Main
System 1 is the default first decision point; its plugin settings can choose
Tool first. System 1's action eligibility still gates its direct fixed actions.
