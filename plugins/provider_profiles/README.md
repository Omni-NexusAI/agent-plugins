# Provider Profiles

Agent Zero plugin that adds **model favorites** and **provider-aware model memory**
to the model configurator (the preset editor's Main, Vision, Utility and Embedding
slots).

## What It Does

### Model favorites

- A **star** beside the model name (so manually typed names can be favorited) and on
  every row of the model search list.
- Favorites are kept **per model type** (chat, vision, utility, embedding), without a
  limit, and identified by **provider + API base + model name**. Choosing a favorite
  fills Provider, API base and model name together, even when it belongs to another
  provider.
- Opening the field (click, typing, search icon or Enter) shows an **instant favorites
  card** above the normal results: the 5 most recently selected favorites
  (`favorites_shown`), matching ones first while you type, plus **Show all N**. Starring
  counts as use. The normal results stay underneath.
- Opening a field that already holds a value lists **all** models (matches first);
  typing narrows the list. Agent Zero itself only lists near-matches of the current
  text. Set `normal_results_mode: core` to get exactly that behavior back.
- Favorites live on the server in `usr/plugins/provider_profiles/favorites.json`
  (shared by every browser, removed with the plugin, `.bak` copy, corrupt files are
  quarantined). They are never stored in the plugin `config.json`, whose Save/Reset
  replaces the whole file.

### Provider memory

- Remembers the last model per provider and model slot, so switching away from a
  provider and back restores that provider's model, `api_base`, context length and
  other model settings (secrets such as API keys are never stored).
- Keeps `kwargs` and their text mirror in sync (needed on Agent Zero v2.14, whose Save
  rebuilds `kwargs` from the text).
- Auto-fills local provider API bases for LM Studio and Ollama; optionally clears a
  stale model name when switching to a provider with no saved selection.

## Compatibility

| Host | Status |
|---|---|
| Agent Zero **v2.14** (latest at release time) | supported; verified in an offline harness on the pinned v2.14 source, not yet on a live instance |
| Agent Zero **v2.11** | supported (compatibility floor); same offline verification on the pinned v2.11 source |
| Agentspine | **not supported** (it ships its own `_provider_profiles`; its startup sanitizer archives this plugin) |

- Plugin-only and additive: no host file is edited, nothing is shipped through
  `conf/model_providers.yaml`, and all names are namespaced (`pp-` CSS prefix,
  `__providerProfiles*` globals, `/api/plugins/provider_profiles/*`).
- Fails soft: if the favorites API, Alpine, the `modelConfig` store or the model
  field is missing, the host dropdown works exactly as before.
- If Agent Zero ever ships its own model favorites (a public `modelConfig` store member
  whose name contains "favorite"), the favorites UI steps aside (`favorites_ui: auto`).
- Emergency switch without opening settings: run
  `localStorage.setItem("pp_favorites_ui", "off")` in the browser console and reload.

### Host dependencies (re-checked before every Agent Zero upgrade)

The favorites UI relies on these parts of Agent Zero's `_model_config` plugin:

- `input[x-model="model.name"]` inside a `.field-control` whose Alpine scope exposes
  `model`, `modelType`, `results`, `open`, `searching`, `doSearch()`;
- two `.model-search-results` containers with `.model-search-item` rows (keyed by id,
  scope variable `m`);
- `Alpine.store("modelConfig")` members `searchModelsDetailed(provider, query, modelType, apiBase)`
  (v2.11 reaches it through `searchModels`), `groupResults(models, query)`,
  `kwargsToText`, `textToKwargs`, `installSettingsHooks(context)`;
- `select[x-model="model.provider"]` with a change handler that resets `api_base`/`kwargs`;
- the `modal-content-loaded` DOM event and `POST /api/plugins/_model_config/model_search`.

Before upgrading Agent Zero, check the target release (read-only, public GitHub files):

```bash
python tests/compat/check_upstream.py v2.15
```

It prints a PASS/WARN/FAIL table for every dependency above and compares the files
with the pinned v2.11 and v2.14 fixtures.

## Installation

1. Copy the `provider_profiles` folder into Agent Zero's `/a0/usr/plugins/` directory.
2. Restart Agent Zero (API handlers are loaded at startup) or toggle the plugin.
3. Open Settings > Agent > Model presets: stars appear beside the model name fields.

## Configuration

Edit from the plugin Settings screen. Missing keys fall back to the defaults below.

| Key | Default | Description |
|---|---|---|
| `favorites_ui` | `auto` | `auto` (off if the host has its own favorites), `on`, `off` |
| `favorites_shown` | `5` | Favorites pinned in the card (1-20); the rest are behind "Show all N" |
| `normal_results_mode` | `narrow` | `narrow`: full list when opened, typing narrows. `core`: exactly like Agent Zero |
| `local_provider_defaults.lm_studio` | `http://host.docker.internal:1234/v1` | API base filled in for LM Studio |
| `local_provider_defaults.ollama` | `http://host.docker.internal:11434` | API base filled in for Ollama |
| `clear_stale_model_on_new_provider` | `true` | Clear the model name when the new provider has no saved selection |
| `discovery_enabled` | `true` | Ask local inference servers (LM Studio, llama.cpp and routers, Ollama, vLLM, ...) for their models, aliases, state and context. Off: no extra request is made |
| `discovery_fill_on_select` | `false` | When a discovered model is selected, also fill the context length and vision flag from the server's own numbers |

An API base that carries credentials (`user:pass@`) or a query string cannot be
favorited, so secrets never reach `favorites.json`. An empty API base and an explicitly
typed default are different favorites.

## Development

Tests are offline. From this folder:

```bash
python -m unittest discover -s tests -t . -p "test_*.py"   # Python + Playwright DOM harness
node --test "tests/js/*.test.mjs"                          # pure favorites logic
python tests/fixtures/fetch_fixtures.py                    # refresh pinned upstream fixtures
```

The DOM harness runs the real upstream `model-field.html` and `model-config-store.js`
(pinned v2.11 and v2.14 under `tests/fixtures/`, MIT, sha256 manifests) in headless
Chromium against a fake backend; it is skipped when Playwright is not installed.

## License

MIT
