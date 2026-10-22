# Provider Profiles

Agent Zero plugin that adds **model favorites**, **local endpoint model discovery**
and **provider-aware model memory** to the model configurator (the preset editor's
Main, Vision, Utility and Embedding slots).

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

### Local endpoint discovery

For local inference servers the model-name list shows what the server itself reports,
next to Agent Zero's own results (the union of both):

- **Router aliases and configurations are selectable** (and can be starred): llama.cpp
  router rows and their `aliases`, llama-swap and Unsloth Studio models, Strata Router
  configurations, LM Studio and Ollama models. Agent Zero's own search lists bare ids,
  shows only near-matches of the text already in the field (so a long alias hides every
  other configuration) and drops ids that merely contain `embed` or `image`.
- **Chips under each row**: state (`loaded`, `loading`, `sleeping`, `unloaded`,
  `downloading`, `incomplete`, `failed`), the context the server serves or is configured
  for (`128k ctx`; `max 256k` when only the model's ceiling is known), `vision`,
  quantization, the display name and `alias of ...`.
- **A reason instead of a silent "No models found"**: unreachable, host not found,
  timeout, untrusted TLS certificate, missing API key, forbidden, wrong path, unusable
  answer, redirect or a name that points at both local and public addresses, each with a hint (inside Docker, `localhost` is the container
  itself: use `host.docker.internal`). Catalog suggestions that Agent Zero falls back to
  for a failing local server are dropped once the server itself answered.
- A muted last line names the server that answered, for example
  `llama.cpp router · host.docker.internal:8080 · 7 models`.
- Selecting a model changes nothing but its name, unless `discovery_fill_on_select` is
  on: then the context length (what the server serves, else what it is configured for;
  never the model's maximum) and the vision flag come from the server.
- The dropdown never waits more than 3 seconds for discovery. If a server is slower,
  Agent Zero's own list stands and the chips appear when the answer arrives.

Supported servers (response shapes come from each project's documentation and source and
are covered by fixture tests; they have not been checked against every server version):

| Server | Read from | Pick provider |
|---|---|---|
| llama.cpp router | `GET /v1/models` (per row `status`, `aliases`, tags, launch settings for context and vision) | llama.cpp or Other |
| llama.cpp single server | `GET /v1/models`, `GET /props` (served context, vision, sleeping) | llama.cpp |
| LM Studio | `GET /api/v1/models`, else `/api/v0/models`, else `/v1/models` | LM Studio |
| Ollama | `GET /api/tags`, `GET /api/ps` (running models) | Ollama |
| llama-swap, Unsloth Studio | `GET /v1/models` (state, aliases, context) | Other |
| Strata Router | `GET /v1/models`, `GET /status` | its custom provider |
| vLLM, oMLX, any OpenAI-compatible server | `GET /v1/models` | vLLM, oMLX or Other |

What discovery never does:

- It only sends `GET` requests to the fixed paths above: no model is ever loaded,
  unloaded or reloaded, no query string is sent (llama.cpp treats `?reload=` as a
  command) and no autoloading endpoint is called.
- It only contacts loopback, private (RFC 1918 / ULA) and Tailscale-range (100.64.0.0/10)
  addresses. Link-local and cloud-metadata addresses are refused and public hosts are
  skipped (Agent Zero's own search covers cloud providers). The connection goes to the
  address that was checked, so a second DNS answer cannot redirect it. Redirects are not
  followed.
- Answers larger than 2 MiB are rejected; a call makes at most 3 requests (4 s each).
  Results are cached for 15 s on the server and 5 s in the browser. Failures are never
  cached on the server and are remembered for only 3 s in the browser; a "not a local
  host" answer is remembered for 2 minutes.
- The API key is the stored key of the selected provider (the first one when several are
  stored, without advancing Agent Zero's key rotation) and is sent only to a host that
  passed the check. Keys typed in the UI but not saved are never sent (same as Agent
  Zero's own search). Keys never appear in a response.
- llama.cpp launch settings (`status.args`, `status.preset`, which can hold `--api-key`)
  are never forwarded: only the context size and a vision flag are derived from them.
- Error texts are fixed messages; a server's response body never reaches the browser.
- Proxy settings from the environment are ignored (the request must reach the checked
  address). TLS trust follows the same environment as Agent Zero's own calls
  (`SSL_CERT_FILE` / `SSL_CERT_DIR`); this plugin never changes it.

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
  field is missing, the host dropdown works exactly as before. The same holds for
  discovery: if its API or modules are unavailable, the list is Agent Zero's own.
- If Agent Zero ever ships its own model favorites (a public `modelConfig` store member
  whose name contains "favorite"), the favorites UI steps aside (`favorites_ui: auto`);
  discovery is a separate feature and keeps working.
- With `favorites_ui: off`, `normal_results_mode: core` and `discovery_enabled: false` the
  model fields behave exactly like stock Agent Zero (no extra request, no extra DOM).
- Emergency switch without opening settings: run
  `localStorage.setItem("pp_favorites_ui", "off")` in the browser console and reload
  (switches off everything this plugin adds to the model fields).

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
- the `modal-content-loaded` DOM event and `POST /api/plugins/_model_config/model_search`;
- for discovery: the `{ models, source, error }` object that `searchModelsDetailed`
  returns (discovery merges into it; `source: "litellm_registry"` marks catalog
  suggestions), `helpers.providers.get_provider_config(model_type, provider)` with
  `kwargs.api_base` and `models_list.default_base`, and the stored API key through
  `models.get_api_key_raw` (v2.14) or the same dotenv lookups (`API_KEY_<P>`,
  `<P>_API_KEY`, `<P>_API_TOKEN`) on v2.11, whose `get_api_key` advances a key rotation.

Before upgrading Agent Zero, check the target release (read-only, public GitHub files):

```bash
python tests/compat/check_upstream.py v2.15
```

It prints a PASS/WARN/FAIL table for every dependency above and compares the files
with the pinned v2.11 and v2.14 fixtures.

## Installation

1. Copy the `provider_profiles` folder into Agent Zero's `/a0/usr/plugins/` directory.
2. Restart Agent Zero (API handlers are loaded at startup) or toggle the plugin.
3. Open Settings > Agent > Model presets: stars appear beside the model name fields; for
   a local provider (LM Studio, llama.cpp, Ollama, ...) the list shows state and context
   chips.

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
| `discovery_enabled` | `true` | Ask local inference servers (LM Studio, llama.cpp and routers, Ollama, vLLM, ...) for their models, aliases, state and context. Off: no extra request is made. Switching it on later needs a page reload |
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
UPDATE_VECTORS=1 python -m unittest tests.test_discovery_vectors   # after a deliberate parser change
```

The DOM harness runs the real upstream `model-field.html` and `model-config-store.js`
(pinned v2.11 and v2.14 under `tests/fixtures/`, MIT, sha256 manifests) in headless
Chromium against a fake backend; it is skipped when Playwright is not installed. The
discovery tests talk to stdlib fake endpoint servers (llama.cpp router and single,
LM Studio, Ollama, llama-swap, Unsloth, Strata Router, generic) over real sockets, and
`tests/test_core_search_characterization.py` records what Agent Zero's own search does
against the same servers (the baseline this plugin builds on).

## License

MIT
