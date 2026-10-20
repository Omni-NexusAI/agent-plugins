# Provider Profiles DOX

## Purpose

`provider_profiles` owns provider-aware model memory, per-model-type model favorites, and (planned, second PR) local-endpoint model discovery for official Agent Zero model configuration UIs.

## Sync Status

This is a plugin-local implementation for official Agent Zero. Through 1.0.2 it mirrored the Agentspine `_provider_profiles` overlay byte for byte; from 1.1.0 it diverges on purpose (Agent Zero v2.14 `_kwargs_text` fix, favorites) and Agentspine is not a target: the Spine package `_provider_profiles` is separate and the Spine 9.9 startup sanitizer archives `usr/plugins/provider_profiles`. Profile state still uses the inherited `_provider_profiles` plugin-config namespace (see Local Contracts).

## Ownership

- `README.md` owns user-facing behavior, the compatibility table and the list of host dependencies.
- `default_config.yaml` owns defaults for every setting the code reads (`favorites_ui`, `favorites_shown`, `normal_results_mode`, `local_provider_defaults`, `clear_stale_model_on_new_provider`); `helpers/settings.py` validates and merges them (Agent Zero replaces defaults wholesale once a `config.json` exists).
- `webui/config.html` owns the user-editable settings UI; it must bind every key in `default_config.yaml` and nothing else.
- `helpers/favorites_store.py` owns favorites storage, identity canonicalization and request dispatch; `api/favorites.py` is a thin `ApiHandler` (exactly one handler class per file: the host loader takes the alphabetically last subclass).
- `extensions/webui/page-head/_10_provider_profiles.html` owns provider memory (patching of `modelConfig`, `__providerProfiles` registry incl. `switchProvider`).
- `extensions/webui/page-head/_20_model_favorites.html` is the loader for `webui/favorites-ui.js` (DOM glue), `webui/favorites-core.js` (pure logic), `webui/favorites-api.js`, `webui/store-patch.js` and `webui/favorites.css`.
- `webui/thumbnail.svg` is the canonical blue-server Provider Profiles icon
  (SHA-256 `100083e05d213c528dd7a5ececbdec0d427d9b1628a55e28f14a05b7b14ad877`);
  do not restore the archived three-slider asset.
- `tests/` owns the offline suites; `tests/fixtures/` holds byte-exact pinned upstream Agent Zero files (v2.11, v2.14; MIT) with sha256 manifests and must stay `-text`.

## Local Contracts

- Preserve model selections per provider; preserve API base, context length and other non-secret model fields beside them (never `api_key`, never `_`-prefixed internals).
- After restoring a profile keep `_kwargs_text` in step with `kwargs` (Agent Zero v2.14 rebuilds `kwargs` from the text on Save).
- Preserve local-provider API base defaults for LM Studio and Ollama unless config changes them; clear stale model names only when `clear_stale_model_on_new_provider` says so.
- Degrade safely when the target model config store, the favorites API or the model field is absent: no console errors and the host dropdown unchanged.
- Do not describe this plugin as synced from a container snapshot.

### Host compatibility

- Supported hosts: official Agent Zero **v2.11** (compatibility floor) and **v2.14** (latest when written, 2026-10-13). Newer releases are checked with `tests/compat/check_upstream.py <tag>` before an Agent Zero upgrade; extend the checks and fixtures when a host dependency changes.
- Plugin-only and additive: never edit host files, never ship provider ids through plugin `conf/model_providers.yaml`, namespace everything (`pp-` CSS prefix, `__providerProfiles*` globals, `/api/plugins/provider_profiles/*`).
- Every `Alpine.store("modelConfig")` patch is flag-guarded, forwards all arguments, never creates a missing host member, falls back to the previous implementation on error, and is disposable. No `innerHTML`, `eval` or `window.fetch` patching; plugin-owned DOM uses `textContent` and `x-ignore`.
- With `favorites_ui: off` and `normal_results_mode: core`, request bodies and DOM equal official behavior. `normal_results_mode: narrow` (default) is the one deliberate deviation: the plugin asks the host search for the full list (empty query) so a filled field can browse everything.
- If the host ships native model favorites (a public `modelConfig` member matching `/favou?rite/i`), the plugin yields unless `favorites_ui: on`.

### Favorites

- Per model type (`chat`, `vision`, `utility`, `embedding`); unlimited (cap 1000 per type, explicit error); identity is provider + canonical API base + model name. Canonical API base: trim, lowercase scheme and host, drop default port, strip trailing slash and one trailing `/v1`; credentials or query strings are rejected. The Python and JS rules are pinned by `tests/vectors/identity_vectors.json`; an empty base and an explicit default are different favorites.
- Starring counts as use. The card pins the `favorites_shown` most recently selected favorites (matching first while typing) with "Show all N". Choosing a favorite fills Provider (through `__providerProfiles.switchProvider`), API base and name.
- Storage is server-side `usr/plugins/provider_profiles/favorites.json` (removed with the plugin), never the plugin `config.json`. Writes are idempotent server-side operations under a lock file (module-level locks are unsafe: the host purges plugin modules), atomic with a `.bak`; corrupt files are quarantined.
- The favorites UI must not add a second body-wide observer; it mounts per modal (`modal-content-loaded`) and per field.

### Local Discovery (planned, second PR)

- Layers on top of the host `model_search`; never replaces it. Server-side and GET-only, gated on the resolved IP class (loopback, RFC1918, CGNAT allowed; link-local and metadata blocked), no redirects, no query strings, first stored API key only and only sent to private hosts, no model load or unload call ever, llama.cpp `status.args` / `status.preset` never forwarded.

## Work Guidance

- Keep `plugin.yaml`, the `VERSION` constants in the page-head files and `favorites-ui.js`, `README.md`, `default_config.yaml`, `webui/config.html` and this file aligned (`tests/test_hygiene.py` enforces the mechanical parts).
- Preserve unknown model/provider fields when saving profiles.
- Keep local-provider defaults in config and docs aligned.
- Use Alpine's public `$data(element)` context for preset-editor model fields; retain the settings-context fallback for older direct-settings layouts.
- Keep pure logic in `webui/favorites-core.js` (no DOM, Alpine or network) so it stays unit-testable.

## Verification

Run from this folder (offline):

- `python -m unittest discover -s tests -t . -p "test_*.py"` (store, handler, hygiene, compat probe, Playwright DOM harness on pinned v2.11 and v2.14; DOM tests skip without Playwright).
- `node --test "tests/js/*.test.mjs"`.
- `python tests/compat/check_upstream.py <tag>` before upgrading Agent Zero (read-only network).
- Manually: switch provider away and back (model, API base, context and kwargs restore); star a row and a typed name, reload, favorites persist; select a favorite from another provider; load on a host without the store and confirm no errors.
- Live checks on a real Agent Zero instance need the owner's explicit approval.

## Child DOX Index

This plugin has no child DOX files.
