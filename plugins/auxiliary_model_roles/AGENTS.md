# Auxiliary Model Roles DOX

This package owns optional Tool and Coding model roles for Agent Zero. Its
config, UI, delegation tool, and model helper stay within this folder.
The inline model controls and plugin page save global plugin config, so the
manifest does not enable per-project or per-agent config scopes.
Use Agent Zero's provider list, in-field model search, inline masked API key
control, and API base field conventions. Keep provider keys in the native key
store rather than plugin config.

Main owns delegation. Tool may submit one strict JSON request through the
native host executor; it never runs a tool directly. Every call reads
current enablement so disabling a role takes effect on the next dispatch.
The plugin can run without System 1. When System 1 is installed, its optional
finite-choice route may invoke the same delegation tool through the host.

Verify both rendered UI states and live host permissions before review-ready.

Multimodal embedding: media capability is declared per `provider/model` under
`embedding.models` and confirmed by Check server; never infer it from a name or
fall back to another model. Text embedding stays native. Media vectors must use
the model and dimensions the memory index was built with (`embedding.json`).
Media documents keep `media_*` metadata; `repair` restores media vectors after a
text rebuild. Check server sends samples only on click; keys stay server-side.
Live-test changes with the real llama-server (not only the HTTP stub).
