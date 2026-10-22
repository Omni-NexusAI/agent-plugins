"""Read-only helpers for fetching files from upstream agent0ai/agent-zero.

Only HTTP GETs of public files are made. Nothing is cloned or written except
by the callers that explicitly save the returned bytes.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request

REPO = "agent0ai/agent-zero"
RAW = f"https://raw.githubusercontent.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}"

# Upstream files this plugin depends on (host selectors, store methods, search endpoint).
WATCHED = [
    "plugins/_model_config/webui/model-field.html",
    "plugins/_model_config/webui/model-config-store.js",
    "plugins/_model_config/webui/api-keys-mixin.js",
    "plugins/_model_config/webui/switcher-mixin.js",
    "plugins/_model_config/api/model_search.py",
    "models.py",
    "helpers/providers.py",
    "conf/model_providers.yaml",
    "webui/vendor/alpine/alpine.min.js",
]

# Pinned hosts the fixtures and the DOM harness are built from.
PINNED = {
    "v2.11": "6a6cecff8527b164668c7a6ab2f76b6b1ed7cfa1",
    "v2.14": "ff2a5b9c9c4e490ba38dd7c313e779510bb2071a",
}


def _get(url: str, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "provider-profiles-compat/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https hosts
        return response.read()


def resolve_ref(ref: str) -> str:
    """Resolve a tag, branch or sha to a full commit sha."""
    if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref):
        return ref
    data = json.loads(_get(f"{API}/commits/{ref}"))
    return data["sha"]


def fetch(ref_sha: str, path: str) -> bytes:
    return _get(f"{RAW}/{ref_sha}/{path}")


def fetch_or_none(ref_sha: str, path: str) -> bytes | None:
    try:
        return fetch(ref_sha, path)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
