# Native Tool Output Contract

Optional structured output for an explicitly verified OpenRouter Chat Completions
model. Agent Zero's native tool parser requires a JSON tool request; an unconstrained
model can instead emit plain prose, even after receiving the correct remote answer.
This plugin requests the native envelope from the provider before generation.
It never turns existing prose into a successful response or executes a tool.

Copy this complete folder into `usr/plugins/`. After verifying current model and
provider support, configure `config.json` with exact native `model_name` values:

```json
{"models": ["openrouter/deepseek/deepseek-v4.1-flash-1017"]}
```

Then enable through the normal plugin manager. The distributed default list is
empty. The example is the model checked in the November 5 development run, not
a promise of support for other models, versions or future provider changes.

The supported `chat_model_call_before` hook supplies a cloned model/kwargs for
that call only: `response_format: json_schema` with required `thoughts`, `headline`,
`tool_name`, and object `tool_args`, plus `provider.require_parameters: true`.
Model/provider settings and chat history are unchanged. Existing format requests,
Responses mode, unlisted models/providers and unsupported host interfaces bypass it.
Disabling restores the original request parameters on subsequent calls.

The model still chooses its tool, arguments and answer. Tool-specific argument
validation, receipt truthfulness, task state and goal completion remain native.
A valid envelope can still contain wrong arguments; this is no general reasoning
or task-reliability guarantee. Unsupported-provider errors are not retried without
the contract. The plugin changes neither A2A format compatibility nor peer routing.

OpenRouter documents [structured output and capability checks](https://openrouter.ai/docs/guides/features/structured-outputs)
and [requiring provider parameter support](https://openrouter.ai/docs/guides/routing/provider-selection).
Development verification: one synthetic request through a clone of the existing
native model sent the schema and require_parameters on the actual wire, returned
a valid native response envelope with the exact synthetic acknowledgment, and
left the original model kwargs unchanged. The reviewed ordinary named-peer test
then completed with one native A2A call, the actual remote reply, and a valid
native final response while Unifier was disabled. See [VERIFICATION.md](VERIFICATION.md)
for the tested scope and limitations.

Run `python plugins/native_tool_output_contract/tests/test_contract.py`.
