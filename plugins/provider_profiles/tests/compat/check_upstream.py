"""Check an upstream Agent Zero release against what this plugin depends on.

Usage (from the plugin directory; read-only HTTPS GETs of public files):

    python tests/compat/check_upstream.py            # latest GitHub release
    python tests/compat/check_upstream.py v2.15      # a tag, branch or commit
    python tests/compat/check_upstream.py v2.14 main

Prints a PASS / WARN / FAIL table and exits 1 when any FAIL is found. Run it before
upgrading Agent Zero. The dependency list mirrors "Host dependencies" in README.md.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import upstream  # noqa: E402

FIELD = "plugins/_model_config/webui/model-field.html"
STORE = "plugins/_model_config/webui/model-config-store.js"
SEARCH = "plugins/_model_config/api/model_search.py"
MODELS = "models.py"
PROVIDERS = "helpers/providers.py"
ALPINE = "webui/vendor/alpine/alpine.min.js"
FILES = (FIELD, STORE, SEARCH, MODELS, PROVIDERS, ALPINE)
FIXTURES = HERE.parent / "fixtures"


def _js_without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))


def evaluate(files: dict[str, str]) -> list[tuple[str, str, str]]:
    """Return (status, check, detail) rows for the given upstream file contents."""
    rows: list[tuple[str, str, str]] = []

    def check(ok: bool, name: str, detail: str, *, warn: bool = False):
        rows.append(("PASS" if ok else ("WARN" if warn else "FAIL"), name, detail))

    field = files.get(FIELD)
    store = files.get(STORE)
    search = files.get(SEARCH)
    models = files.get(MODELS)
    providers = files.get(PROVIDERS)
    alpine = files.get(ALPINE)

    if field is None:
        check(False, "model-field.html present", FIELD)
    else:
        scope = re.search(r'class="field-control"[^>]*x-data="(.*?)"\s*@click\.outside', field, flags=re.S)
        scope_text = scope.group(1) if scope else ""
        check('x-model="model.name"' in field, "model name input", 'input[x-model="model.name"]')
        check(bool(scope) and all(k in scope_text for k in ("results", "open", "searching", "doSearch")),
              "field-control scope", "x-data exposes results, open, searching, doSearch")
        check(field.count('class="model-search-results"') >= 2, "two result containers", ".model-search-results x2")
        check('class="model-search-item' in field and 'x-text="m"' in field and re.search(r'x-for="m in grouped\(\)', field) is not None,
              "result rows", ".model-search-item rows keyed by scope variable m")
        check("searchModelsDetailed(" in field or "searchModels(" in field, "search call", "searchModelsDetailed / searchModels")
        check("$store.modelConfig.groupResults(" in field, "group results call", "grouped() uses store.groupResults")
        selects = re.findall(r"<select\b.*?</select>", field, flags=re.S)
        check(any('x-model="model.provider"' in block and "@change=" in block for block in selects),
              "provider select with change handler", 'select[x-model="model.provider"] @change')
        check("@click.outside" in field, "click outside closes list", "@click.outside")
        check("model-search-btn" in field, "search button", ".model-search-btn")
        native = re.search(r"(?i)favou?rite", field) is not None
        check(not native, "no native favorites markup in field", "plugin would yield" if native else "none", warn=True)

    if store is None:
        check(False, "model-config-store.js present", STORE)
    else:
        code = _js_without_comments(store)
        check('createStore("modelConfig"' in code, "store registered as modelConfig", 'createStore("modelConfig"')
        check(re.search(r"async\s+searchModelsDetailed\s*\(", code) is not None, "searchModelsDetailed", "async searchModelsDetailed(")
        check(re.search(r"\bgroupResults\s*\(", code) is not None, "groupResults", "groupResults(")
        check("kwargsToText" in code and "textToKwargs" in code, "kwargs helpers", "kwargsToText / textToKwargs")
        check(re.search(r"\binstallSettingsHooks\s*\(", code) is not None, "installSettingsHooks", "installSettingsHooks(")
        detailed = re.search(r"async\s+searchModelsDetailed\s*\(.*?\n  \},", code, flags=re.S)
        body = detailed.group(0) if detailed else ""
        check(re.search(r"\bmodels:\s*data\.models", body) is not None, "search result carries models",
              "searchModelsDetailed returns { models: data.models, ... } (discovery merges into it)")
        check("source:" in body and "error:" in body, "search result carries source and error", "{ source, error } (catalog suggestions, host toast)", warn=True)
        native_keys = sorted({m for m in re.findall(r"(?m)^\s{2}(?:async\s+)?([A-Za-z]\w*)\s*[(:]", code) if re.search(r"(?i)favou?rite", m)})
        check(not native_keys, "no native favorites store members", ", ".join(native_keys) or "none", warn=True)

    if search is None:
        check(False, "model_search.py present", SEARCH)
    else:
        check(re.search(r"class\s+\w+\(ApiHandler\)", search) is not None, "ApiHandler subclass", "class ...(ApiHandler)")
        check('"models"' in search and '"source"' in search and '"error"' in search, "response keys", "models, source, error")
        check('input.get("query"' in search, "query input", 'input.get("query"')
        check('input.get("api_base"' in search, "api_base input", 'input.get("api_base"')
        check('"default_base"' in search and '"models_list"' in search, "provider default base", "models_list.default_base (discover_models resolves the same base)", warn=True)

    # Local endpoint discovery (api/discover_models.py) reads the stored key and the provider config like the host search.
    if models is None:
        check(False, "models.py present", MODELS)
    else:
        check(re.search(r"(?m)^def get_api_key\(", models) is not None, "get_api_key", "def get_api_key(service)")
        lookups = all(token in models for token in ('f"API_KEY_{service.upper()}"', 'f"{service.upper()}_API_KEY"', 'f"{service.upper()}_API_TOKEN"'))
        check(lookups, "stored key lookups", "API_KEY_<P>, <P>_API_KEY, <P>_API_TOKEN (the v2.11 fallback mirrors them)", warn=True)
        raw = re.search(r"(?m)^def get_api_key_raw\(", models) is not None
        check(True, "get_api_key_raw", "present: the first stored key is read without advancing the round robin" if raw else "absent: the dotenv lookups are used")
    if providers is None:
        check(False, "helpers/providers.py present", PROVIDERS)
    else:
        check(re.search(r"(?m)^def get_provider_config\(", providers) is not None, "get_provider_config", "def get_provider_config(provider_type, provider_id)")

    if alpine is not None:
        version = re.search(r'version:"(\d+)\.(\d+)\.(\d+)"', alpine)
        check(bool(version) and version.group(1) == "3", "Alpine 3.x", version.group(0) if version else "version not found", warn=True)
    return rows


def _pinned_comparison(files_bytes: dict[str, bytes]) -> str:
    notes = []
    for name in ("v2.11", "v2.14"):
        manifest_path = FIXTURES / f"a0-{name}" / "MANIFEST.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
        same = [p for p, data in files_bytes.items() if p in manifest and manifest[p]["sha256"] == upstream.sha256(data)]
        diff = [p for p in files_bytes if p in manifest and p not in same]
        notes.append(f"{name}: {len(same)} identical, {len(diff)} changed" + (f" ({', '.join(Path(p).name for p in diff)})" if diff else ""))
    return "; ".join(notes)


def latest_release_tag() -> str:
    request = urllib.request.Request(f"{upstream.API}/releases/latest", headers={"User-Agent": "provider-profiles-compat/1"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())["tag_name"]


def main(argv: list[str]) -> int:
    refs = argv or [latest_release_tag()]
    failed = False
    for ref in refs:
        sha = upstream.resolve_ref(ref)
        raw = {path: upstream.fetch_or_none(sha, path) for path in FILES}
        files = {path: data.decode("utf-8", "replace") for path, data in raw.items() if data is not None}
        print(f"\n== {ref} ({sha[:10]}) ==")
        for status, name, detail in evaluate(files):
            print(f"  {status:<4}  {name:<40} {detail}")
            failed = failed or status == "FAIL"
        print("  info  " + _pinned_comparison({p: d for p, d in raw.items() if d is not None}))
    print("\nResult:", "FAIL (review before upgrading)" if failed else "no blocking differences")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
