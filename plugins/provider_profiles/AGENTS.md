# Provider Profiles DOX

## Purpose

`provider_profiles` owns provider-aware model memory for compatible Agent Zero model configuration UIs.

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
