# Native Tool Output Contract DOX

This separate opt-in plugin owns only per-call provider request parameters.
It is neither A2A Format Unifier nor a model-output repair/parser. Never merge
it with protocol conversion, native peer discovery or task-history changes.

The supported chat_model_call_before hook may replace call_data.model with a
shallow model copy owning a deep copy of kwargs. An explicit verified OpenRouter
model allowlist, Chat Completions mode, no existing response_format, and the
host's model_copy interface are required. Preserve other models/modes and any
existing user format. Blank/malformed config is inert. Never mutate shared
provider/model settings, native source, messages, genuine history, callbacks,
credentials or global LiteLLM switches.

The request asks for the generic native thoughts/headline/tool_name/tool_args
JSON envelope and requires a supporting provider. It does not choose a tool,
force response/completion, validate every tool's arguments, create receipts,
convert prose into success, retry requests, dispatch tools, or rewrite replies.
Provider rejection remains a normal error; never remove constraints and retry.

No network is called by the hook/helper. Independently verify the configured
model's structured_outputs/response_format support and one synthetic request
before activation. Runtime models[] and toggles stay out of distribution.

Run tests/test_contract.py. Live ordinary acceptance still requires the actual
native peer reply and a correct final response after one send; a schema fixture
or correct JSON envelope does not alone pass that gate.
