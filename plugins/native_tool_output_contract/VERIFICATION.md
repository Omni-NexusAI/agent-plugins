# Verification — November 5, 2026

- Eleven isolated checks passed, covering exact model/provider/mode gating,
  the current native `chat` alias, preservation of top-level and nested existing
  contracts, deep kwargs isolation, concurrent clones and hook-only replacement
  of the per-call model. The envelope does not force a tool or invent an answer.
- Current public OpenRouter endpoint metadata advertised structured outputs for
  the tested model. One synthetic-only request through a cloned native model
  sent `json_schema` and `provider.require_parameters=true` on the actual wire,
  returned the exact synthetic acknowledgment in a native response envelope in
  2.6 seconds, and left original kwargs unchanged. No private chat was replayed.
- Independent review required nested-contract conflict guards and validation
  against the running desktop `/a0` runtime, not an unrelated checkout. Both were
  addressed before live activation. The running wrapper uses mode `chat`.
- An isolated subprocess then exercised the actual native extension loader,
  disabled/enabled/disabled discovery, real native model copying and the native
  LiteLLM transport with mocked nonstreaming and streaming HTTP responses.
  Both prepared requests retained the schema and require_parameters. Original
  kwargs and disabled model identity were unchanged. Every socket connection
  was blocked for the entire subprocess, including imports, using LiteLLM's
  bundled offline cost metadata. No live plugin was installed by that fixture.
  An earlier scoped mock allowed the SDK's public import-time metadata lookup;
  it is not counted as the full-process zero-egress validation.
- The reviewed live candidate was enabled only for the exact verified desktop
  OpenRouter DeepSeek model. An ordinary default-chat request named the laptop
  native Agent Zero without supplying a URL, token or schema instruction.
  The separate contact directory supplied explicit native metadata. With
  Unifier disabled, one native A2A call received a real reply and the agent
  returned that reply through native `response` with a `text` argument.
  Completion took 116 seconds; there were no format warnings or repeated calls.
- Nine protected native source/model/settings/environment/secret files remained
  byte-identical. The native peer credential was absent from the model window
  and serialized chat. No process restart, provider setting change, history edit,
  reply conversion or synthetic successful answer was performed.

This proves the single tested ordinary workflow, not sustained reliability or
support for other models/backends. Tool-specific arguments are still validated
natively. Other models remain inert unless separately verified and configured.
