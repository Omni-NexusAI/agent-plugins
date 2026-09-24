# System 1 for Agent Zero

This plugin adds finite-choice routing in front of Agent Zero's Main model.
It supports TypeSafe Jev directly, Jev through OpenRouter's Decisions API,
the `parallel-decision` llama.cpp fork's `POST /v1/decision`, and the host's
standard chat providers for bounded routing. Configure existing services; installation never
downloads a model or starts a server. The standard llama.cpp server does not
provide this decision endpoint.

The plugin is disabled by default. In the Main, Utility, and Embedding model
sections, enable **System One Mode** and select a backend, model, and endpoint.
When Main mode is enabled, each eligible decision appears as an expandable **S1**
step in the chat process timeline. It shows whether System 1 selected an
eligible action, delegated to a specialist, or handed off to Main, plus backend,
elapsed time, and confidence when available. Native Gen and Tool steps remain
unchanged. For a selected action, S1 names the tool submitted to Agent Zero;
the native Tool step shows its actual execution and result. The S1 detail
intentionally omits request text and tool arguments.
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
contains a fixed `tool_name` and nonempty `tool_args`. The decision model cannot generate
arbitrary arguments. Agent Zero still validates and executes the chosen tool
under its usual permissions and history. After a nonterminating action, the
plugin waits for the host to record that tool's result before requesting another
finite decision. The action count is bounded by `max_actions_per_turn` (default
three, maximum eight), and an action ID cannot repeat within a turn. A tool
error or missing result goes to Main. Empty or uncertain choices, service
errors, and open-ended work also go to Main. With an empty action map, System 1
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
      share_result_with_backend: true
      return_result_to_user: false
```

`share_result_with_backend` sends at most `max_result_chars` (default 2000)
of the observed result to the next decision. It is false by default.
`return_result_to_user` separately permits System 1 to choose a fixed finish
route that returns the observed result without rewriting it. Use it only for
tools whose complete result is suitable for display; truncated results cannot
take that finish route. The two permissions are independent.

Only configure actions whose exact tool schema and permissions you have
verified on the installed Agent Zero version. There is no automatic local to
hosted fallback.
