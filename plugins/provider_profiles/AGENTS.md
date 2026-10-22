# Provider Profiles DOX

## Purpose

`provider_profiles` owns provider-aware model memory, per-model-type model favorites and local-endpoint model discovery (llama.cpp routers and aliases, LM Studio, Ollama, other OpenAI-compatible servers) for official Agent Zero model configuration UIs.

## Sync Status

This is a plugin-local implementation for official Agent Zero. Through 1.0.2 it mirrored the Agentspine `_provider_profiles` overlay byte for byte; from 1.1.0 it diverges on purpose (Agent Zero v2.14 `_kwargs_text` fix, favorites; local endpoint discovery from 1.2.0) and Agentspine is not a target: the Spine package `_provider_profiles` is separate and the Spine 9.9 startup sanitizer archives `usr/plugins/provider_profiles`. Profile state still uses the inherited `_provider_profiles` plugin-config namespace (see Local Contracts).

## Ownership

- `README.md` owns user-facing behavior, the compatibility table and the list of host dependencies.
- `default_config.yaml` owns defaults for every setting the code reads (`favorites_ui`, `favorites_shown`, `normal_results_mode`, `local_provider_defaults`, `clear_stale_model_on_new_provider`, `discovery_enabled`, `discovery_fill_on_select`); `helpers/settings.py` validates and merges them (Agent Zero replaces defaults wholesale once a `config.json` exists).
- `webui/config.html` owns the user-editable settings UI; it must bind every key in `default_config.yaml` and nothing else.
- `helpers/favorites_store.py` owns favorites storage, identity canonicalization and request dispatch; `api/favorites.py` is a thin `ApiHandler` (exactly one handler class per file: the host loader takes the alphabetically last subclass).
- `helpers/endpoint_parsers.py` owns the pure response parsers and the normalized entry shape; `helpers/endpoint_discovery.py` owns the address gate, pinned HTTP, probe plans, key selection, errors and cache; `api/discover_models.py` is the thin `ApiHandler` that injects the host's provider config and key store.
- `extensions/webui/page-head/_10_provider_profiles.html` owns provider memory (patching of `modelConfig`, `__providerProfiles` registry incl. `switchProvider`).
- `extensions/webui/page-head/_20_model_favorites.html` is the loader for `webui/favorites-ui.js` (field controller shared by favorites and discovery), `webui/favorites-core.js` (pure logic), `webui/favorites-api.js`, `webui/store-patch.js` and `webui/favorites.css`; it also loads the optional discovery modules `webui/discovery-ui.js` (store wrapper, row chips, notes), `webui/discovery-merge.js` (pure: normalization, union, chips, fill) and `webui/discovery-api.js` with `Promise.allSettled`, so a failed discovery module never costs the favorites.
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

### Local Discovery (1.2.0)

- **Baseline first**: `tests/test_core_search_characterization.py` runs the pinned upstream `model_search.py` (v2.11 and v2.14) against fake endpoint servers and records what the host already does (ids only, text filtering, name-based drops, silent failures, auth handling, registry fallback). Discovery closes measured gaps only; the host stays the baseline. If a host release changes one of those measurements the matching test fails and discovery must be re-checked.
- Layers on top of the host `model_search`; never replaces it or edits its request. Server side, GET only: `api/discover_models.py` (thin handler; injects the host's provider config and key store), `helpers/endpoint_discovery.py` (gate, pinned HTTP, probe plans, key choice, errors, cache), `helpers/endpoint_parsers.py` (pure parsers, entry shape). Browser side: `webui/discovery-ui.js`, `webui/discovery-merge.js`, `webui/discovery-api.js`.
- Gate on the **resolved IP class**: loopback, RFC1918/ULA and CGNAT (100.64/10) are probed; link-local and metadata (169.254/16, fe80::/10, the cloud metadata addresses), unspecified, multicast and reserved are refused (`blocked`); public hosts are skipped (`skipped: public_host`, the host search covers cloud providers); a host with any non-local answer is not probed. The name is resolved once; the connection goes to a checked address (IPv4 first, at most two, the next only after a refused connection) while the entered name stays in `Host`, SNI and certificate verification.
- No redirects, no query strings (llama.cpp `?reload=`), http(s) only, no proxy or environment trust (`trust_env=False`), 2 MiB response cap while streaming, at most 3 requests per call at 4 s each (10 s per call), success-only 15 s cache in a module dict (no shared asyncio futures: the host may run requests on different event loops). TLS trust is `httpx`'s default plus `SSL_CERT_FILE` / `SSL_CERT_DIR` exactly like the host's own calls; this plugin never sets them (private CAs are the operator's environment). `tests/test_endpoint_discovery.py` pins the request paths as literals with an AST check (no load/unload/reload endpoint can be built) and the absence of write methods.
- API key: the first stored key only (`models.get_api_key_raw` when present, otherwise the same dotenv lookups, because v2.11's `get_api_key` advances the multi-key round robin); `None`, placeholder and non-header-safe keys count as no key; sent only to hosts that passed the gate; never in a response or a cache key. Unsaved UI keys are never sent (same as the host). No custom headers are forwarded.
- Never any model load, unload, `?reload` or autoloading `/props?model=` call; llama.cpp `status.args` / `status.preset` are never forwarded (they can hold `--api-key`); only derived numbers and booleans (context, vision) leave the parser; response bodies never appear in errors (fixed messages built from host:port, provider id and a status code).
- Response `{ok, skipped, endpoint{kind,label,host,requests,cached}, entries, error{category,message,hint}}`; `skipped` is `disabled | no_provider | no_base | public_host`. Entries are `{id, label, aliases, state, failed, context{served|max|configured}, vision, kind, quant}` (state vocabulary `loaded | loading | sleeping | unloaded | downloading | incomplete | downloaded | unknown`; `kind` only from the server's own tags, never guessed from the name). Error categories `unreachable | dns | timeout | tls | tls_protocol | unauthorized | forbidden | not_found | bad_payload | redirect | server_error | blocked | invalid_base`. `tests/vectors/discovery_entries.json` holds the golden parser output that the Python and JS suites both consume.
- UI: favorites and discovery are independent features of one field controller (`favorites-ui.js`). Discovery wraps `searchModelsDetailed` outermost, runs concurrently with the host search under a 3 s deadline (the host result stands when discovery is late, chips follow when it answers), returns the sorted union of ids (router aliases and ids the host's filters dropped appear; `narrow` mode adds everything, `core` mode applies the host's own query rule), drops catalog suggestions once the endpoint answered, never filters local aliases by name, adds chips (state, context, vision, quant, alias, display name), the categorized reason instead of "No models found" (also above catalog suggestions when discovery failed) and a muted endpoint line. Injected nodes use `textContent`, `x-ignore` and no `title` attributes; decoration is idempotent (the row observer must not loop).
- Selecting a row never changes context length or vision unless `discovery_fill_on_select` (default false) is on; then only the served, else configured, context (never the model maximum) and `vision: true` are filled, for chat and utility slots only.
- Flags-off parity needs all three switches: with `favorites_ui: off`, `normal_results_mode: core` and `discovery_enabled: false` the plugin installs nothing, makes no extra request and adds no DOM. `discovery_enabled: false` alone leaves favorites untouched; `favorites_ui: off` alone leaves discovery working (core results mode). The `localStorage` kill switch `pp_favorites_ui=off` disables both.
- Accepted risk: the endpoint can be asked to probe any allowed private address and reports reachability; the same session can already run code through the agent, so this adds no capability.

## Work Guidance

- Keep `plugin.yaml`, the `VERSION` constants in the page-head files and `favorites-ui.js`, `README.md`, `default_config.yaml`, `webui/config.html` and this file aligned (`tests/test_hygiene.py` enforces the mechanical parts).
- Preserve unknown model/provider fields when saving profiles.
- Keep local-provider defaults in config and docs aligned.
- Use Alpine's public `$data(element)` context for preset-editor model fields; retain the settings-context fallback for older direct-settings layouts.
- Keep pure logic in `webui/favorites-core.js` and `webui/discovery-merge.js` (no DOM, Alpine or network; the latter has no sibling imports) so it stays unit-testable.
- A change to a server's response shape starts in `tests/endpoint_payloads.py`, then the parser, then `UPDATE_VECTORS=1 python -m unittest tests.test_discovery_vectors` (review the diff of `tests/vectors/discovery_entries.json`). Never add a request path that is not a literal in `helpers/endpoint_discovery.py`.
- Keep `helpers/endpoint_discovery.py` free of host imports: everything the host provides (provider config, stored key, settings) is injected by `api/discover_models.py`, which keeps the helper testable against fake endpoints without Agent Zero.

## Verification

Run from this folder (offline):

- `python -m unittest discover -s tests -t . -p "test_*.py"` (store, handler, hygiene, compat probe, host-search characterization, parsers, discovery network layer against real fake endpoints, Playwright DOM harness on pinned v2.11 and v2.14; DOM tests skip without Playwright).
- `node --test "tests/js/*.test.mjs"`.
- `python tests/compat/check_upstream.py <tag>` before upgrading Agent Zero (read-only network; also checks the discovery host dependencies).
- Manually: switch provider away and back (model, API base, context and kwargs restore); star a row and a typed name, reload, favorites persist; select a favorite from another provider; load on a host without the store and confirm no errors; with a local server running, open the model list and compare the chips with the server's own state.
- Live checks on a real Agent Zero instance need the owner's explicit approval.

## Child DOX Index

This plugin has no child DOX files.
