# Provider Profiles DOX

## Purpose

`provider_profiles` owns provider-aware model memory, per-model-type model favorites, and (planned, second PR) local-endpoint model discovery for compatible official Agent Zero model configuration UIs.

## Sync Status

`_provider_profiles` was not present in the GPU-pre container sync source `ea634265aca0b0e2567383caf1bc3e8380272566ae59fe08b745adda4ed48c17`. The equivalent provider-history behavior was found in the container's built-in `_model_config` plugin, so this portable plugin mirrors that behavior for hosts where it is not baked in.

## Ownership

- `README.md` owns user-facing behavior and compatibility.
- `default_config.yaml` owns storage keys, local-provider defaults, and stale-model clearing behavior.
- `webui/config.html` owns the user-editable storage key, local provider defaults, and stale-model policy.
- `webui/thumbnail.svg` is the canonical blue-server Provider Profiles icon
  (SHA-256 `100083e05d213c528dd7a5ececbdec0d427d9b1628a55e28f14a05b7b14ad877`)
  shared with the Spine built-in package; do not restore the archived
  three-slider asset.
- WebUI/runtime extension files own patching of `_model_config` / `modelConfig` behavior when available.

## Local Contracts

- Preserve model selections per provider.
- Preserve API base and context length beside model selections.
- Preserve local-provider API base defaults for LM Studio and Ollama unless config changes them.
- Clear stale model names only when the plugin config says to do so.
- Degrade safely when the target model config store is absent.
- Do not describe this plugin as synced from the current GPU-pre container until it is actually present there and copied from that state.

## Host Compatibility Contract (in progress on `feat/provider-profiles-favorites`)

- Supported hosts: official Agent Zero **v2.11** (compatibility floor; what the owner runs today) and **v2.14** (latest when this contract was written, 2026-10-13). Newer releases are checked with `tests/compat/check_upstream.py <tag>` before an Agent Zero upgrade. Agentspine is not a target: its built-in `_provider_profiles` is a separate package and the Spine 9.9 startup sanitizer archives `usr/plugins/provider_profiles`.
- Plugin-only and additive: never edit host files, never ship provider ids through plugin `conf/model_providers.yaml`, and namespace everything (`pp-` CSS prefix, `__providerProfiles` global, `/api/plugins/provider_profiles/*`).
- Every `Alpine.store("modelConfig")` patch is flag-guarded, forwards all arguments, never creates a missing member, falls back to the previous implementation on error, and is disposable.
- With `favorites_ui: off` and `normal_results_mode: core`, request bodies and DOM equal official behavior.
- If the host ships native model favorites, the plugin yields and injects no favorites UI.

## Favorites Contract (in progress)

- Per model type (`chat`, `vision`, `utility`, `embedding`); unlimited (cap 1000 per type, explicit error); identity is provider + API base + model name; the API base is canonicalized (trim, lowercase scheme and host, strip trailing slash and one trailing `/v1`); API bases with credentials or query strings are rejected.
- Starring counts as use. The favorites card pins the most recently selected `favorites_shown` (default 5) and offers "Show all N". Choosing a favorite fills Provider, API base and name together.
- Favorites stay pinned while typing (matching first); typing narrows only the normal results; opening a field that already has a value shows all models, matches first (`normal_results_mode: narrow`, the one deliberate deviation from official request payloads).
- Storage is server-side `usr/plugins/provider_profiles/favorites.json`, never the plugin `config.json` (the Settings page Save/Reset replaces that whole file). Writes are lock-file protected, atomic, with a `.bak` and quarantine of corrupt files.
- The existing per-provider last-model restore stays and is fixed for Agent Zero v2.14 (`_kwargs_text` stays in sync with restored `kwargs`).

## Local Discovery Contract (planned, second PR)

- Layers on top of the host `model_search`; never replaces it. Server-side and GET-only, gated on the resolved IP class (loopback, RFC1918, CGNAT allowed; link-local and metadata blocked), no redirects, no query strings, first stored API key only and only sent to private hosts, no model load or unload call ever, and llama.cpp `status.args` / `status.preset` are never forwarded.

## Work Guidance

- Keep provider history storage key configurable.
- Preserve unknown model/provider fields when saving history.
- Keep local-provider defaults in config and docs aligned.
- Use Alpine's public `$data(element)` context for preset-editor model fields;
  retain settings-context fallback for older direct-settings layouts.

## Verification

- Switch from one provider to another and back; verify prior model selection restores.
- Select LM Studio or Ollama and verify API base defaults are populated.
- Switch to a provider with no saved selection and verify stale model clearing follows config.
- Load on an unsupported host and confirm no unhandled WebUI errors.

## Child DOX Index

This plugin has no child DOX files.
