# System 1 for Agent Zero

This plugin adds finite-choice routing in front of Agent Zero's Main model.
It supports TypeSafe Jev directly, Jev through OpenRouter's Decisions API,
the `parallel-decision` llama.cpp fork's `POST /v1/decision`, and the host's
standard chat providers for bounded routing. Configure existing services; installation never
downloads a model or starts a server. The standard llama.cpp server does not
provide this decision endpoint.

The plugin is disabled by default. In the Main, Utility, and Embedding model
sections, enable **System One Mode** and select a backend, model, and endpoint.
These first-iteration mode settings are global across model presets and agent
profiles; each model category has its own toggle and backend selection.
For hosted Jev, set the configured environment variable (default
`SYSTEM_1_JEV_API_KEY`) through Agent Zero's environment settings. OpenRouter
uses Agent Zero's shared OpenRouter key and its Decisions API; the model
`typesafe/jev-latest` is mapped to OpenRouter's `~typesafe/jev-latest` alias.
Other native chat providers use Agent Zero's model configuration and credentials
for routing, but their self-reported confidence is not trusted for direct fixed
action dispatch. A local
decision endpoint needs no key unless your server requires one.

Main can choose only from `policy.actions` and the Main fallback. Each action
contains a fixed `tool_name` and `tool_args`. The decision model cannot generate
arbitrary arguments. Agent Zero still validates and executes the chosen tool
under its usual permissions and history. Empty or uncertain choices, service
errors, and open-ended work go to Main. With an empty action map, System 1
has no direct actions to dispatch. If Auxiliary Model Roles is installed and
configured, System 1 may delegate a Tool or Coding goal through Agent Zero's
normal `auxiliary_delegate` tool. The specialist result returns to Main.

Utility decisions add conservative instructions to eligible utility requests.
Embedding decisions guide the existing memory plugin's query preparation and
ingestion summaries; the configured embedding model and vector index remain
unchanged. The plugin page has Fast, Balanced, and Conservative starting
presets plus adjustable thresholds and bounded monitoring limits.
The first monitor observes native user interventions while Main works and asks
the host loop to process high-priority ones; it stops after its configured time
or check limit. Other event sources require a future host adapter.

## Fixed action example

```yaml
policy:
  actions:
    recall_project_context:
      description: Recall stored context about the current project.
      tool_name: memory_load
      tool_args:
        query: current project
        limit: 3
```

Only configure actions whose exact tool schema and permissions you have
verified on the installed Agent Zero version. There is no automatic local to
hosted fallback.
