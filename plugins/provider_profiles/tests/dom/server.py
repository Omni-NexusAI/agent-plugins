"""Stdlib HTTP server for the DOM harness.

Serves the harness page, the pinned upstream Agent Zero fixtures (per host
version), the plugin's own WebUI files and a fake backend (model search,
/plugins config, favorites, discover_models). Every request is logged for
assertions. Discovery is backed by the real endpoint_discovery.handle (the code
the API handler runs) and the host search can be backed by the pinned upstream
model_search.py; both then talk to real fake endpoint servers over sockets.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PLUGIN_DIR = Path(__file__).resolve().parents[2]
TESTS_DIR = PLUGIN_DIR / "tests"
DOM_DIR = TESTS_DIR / "dom"
FIXTURES = TESTS_DIR / "fixtures"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}

DEFAULT_MODELS = {
    "openrouter": ["anthropic/claude-x", "deepseek/deepseek-v4", "meta/llama-3", "qwen/qwen3-30b"],
    "lm_studio": ["qwen3-30b-a3b", "gemma-4-12b-it", "llama-3.1-8b"],
    "other": ["router-alias-a", "router-alias-b-vision-160k", "router-alias-c"],
    "huggingface": ["sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-en"],
}


# The pinned upstream search is run under sys.modules stubs (tests/core_search_host.py): never concurrently with itself
# or with discovery, which would otherwise import while the stubs are in place.
CORE_LOCK = threading.Lock()


class HarnessState:
    def __init__(self, host: str):
        self.host = host
        self.requests: list[dict] = []
        self.models = {key: list(value) for key, value in DEFAULT_MODELS.items()}
        self.official_query_filter = True  # emulate model_search.py filtering by query
        self.search_mode = "ok"  # ok | hang | http500
        self.search_delay = 0.0
        self.search_source = "provider_endpoint"
        self.search_error = ""
        self.search_backend = None  # callable(dict) -> dict; replaces the canned list (e.g. the pinned upstream search)
        self.release = threading.Event()
        self.configs: dict[str, dict] = {}
        self.favorites_service = None  # callable(dict) -> dict
        self.favorites_status = 200
        self.discovery_service = None  # callable(dict) -> dict
        self.discovery_status = 200
        self.discovery_mode = "ok"  # ok | hang
        self.discovery_delay = 0.0
        self.blocked_static: set[str] = set()  # file names answered with 404 (e.g. an optional module that failed to load)
        self.lock = threading.Lock()

    def enable_discovery(self, *, settings=None, provider_configs=None, keys=None):
        """Back /discover_models with the real endpoint_discovery.handle (same code the API handler runs)."""
        from ..loader import load_helper

        module = load_helper("endpoint_discovery")
        configs = provider_configs or {}
        merged = {"discovery_enabled": True, **(settings or {})}
        self.discovery_module = module

        def service(body):
            with CORE_LOCK:
                return asyncio.run(module.handle(body, settings=merged, provider_config=lambda model_type, provider: configs.get(provider),
                                                 stored_key=lambda provider: (keys or {}).get(provider)))

        self.discovery_service = service

    def enable_core_search(self, **kw):
        """Back /model_search with the pinned upstream model_search.py of this host version."""
        from ..core_search_host import CoreSearch

        core = CoreSearch(self.host, **kw)

        def backend(body):
            with CORE_LOCK:
                return core.run(str(body.get("provider") or ""), str(body.get("api_base") or ""), str(body.get("query") or ""),
                                str(body.get("model_type") or "chat"))

        self.search_backend = backend

    def enable_favorites(self, directory, overrides=None):
        """Back /favorites with the real FavoritesStore + handle() (same code the API handler runs)."""
        from ..loader import load_helper

        store_mod = load_helper("favorites_store")
        settings_mod = load_helper("settings")
        self.favorites_settings = settings_mod.merge_settings(overrides or {})
        counter = iter(range(1_000_000, 10_000_000))  # deterministic, strictly increasing clock
        self.favorites_store = store_mod.FavoritesStore(Path(directory) / "favorites.json", clock=lambda: float(next(counter)))
        self.favorites_service = lambda body: store_mod.handle(body, self.favorites_store, self.favorites_settings)

    def calls(self, path_suffix: str) -> list[dict]:
        return [r for r in self.requests if r["path"].endswith(path_suffix)]


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "PPHarness/1"

    def log_message(self, *args):  # silence
        pass

    @property
    def state(self) -> HarnessState:
        return self.server.state  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes, content_type: str):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass  # the page navigated away or closed mid-request

    def _json(self, status: int, payload):
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _resolve_static(self, path: str) -> Path | None:
        fixture_root = FIXTURES / f"a0-{self.state.host}"
        if path in ("/", "/harness.html"):
            return DOM_DIR / "harness.html"
        if path == "/vendor/alpine.min.js":
            return fixture_root / "webui/vendor/alpine/alpine.min.js"
        shims = {
            "/js/AlpineStore.js": "AlpineStore.js",
            "/js/api.js": "api.js",
            "/components/plugins/plugin-settings-store.js": "plugin-settings-store.js",
        }
        if path in shims:
            return DOM_DIR / "shims" / shims[path]
        prefix = "/plugins/_model_config/webui/"
        if path.startswith(prefix) and "/" not in path[len(prefix):]:
            return fixture_root / "plugins/_model_config/webui" / path[len(prefix):]
        prefix = "/plugins/provider_profiles/"
        if path.startswith(prefix):
            rel = path[len(prefix):]
            if rel.startswith(("webui/", "extensions/webui/")) and ".." not in rel:
                return PLUGIN_DIR / rel
        return None

    def do_GET(self):
        path = urlsplit(self.path).path
        self.state.requests.append({"method": "GET", "path": path, "body": None})
        target = self._resolve_static(path)
        if target is not None and target.name in self.state.blocked_static:
            target = None
        data = _read_bytes(target) if target else None
        if data is None:
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, data, MIME.get(target.suffix, "application/octet-stream"))

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "{}")
        except ValueError:
            body = {}
        state = self.state
        with state.lock:
            state.requests.append({"method": "POST", "path": path, "body": body})

        if path == "/api/plugins/_model_config/model_search":
            return self._model_search(body)
        if path == "/api/plugins/provider_profiles/discover_models":
            return self._discover(body)
        if path == "/api/plugins":
            return self._plugins(body)
        if path == "/api/plugins/provider_profiles/favorites":
            if state.favorites_status != 200:
                return self._send(state.favorites_status, b"favorites unavailable", "text/plain")
            if state.favorites_service is None:
                return self._send(404, b"no favorites service", "text/plain")
            return self._json(200, state.favorites_service(body))
        self._send(404, b"not found", "text/plain")

    def _model_search(self, body: dict):
        state = self.state
        if state.search_delay:
            threading.Event().wait(state.search_delay)
        if state.search_mode == "hang":
            state.release.wait(timeout=30)
        if state.search_mode == "http500":
            return self._send(500, b"boom", "text/plain")
        if state.search_backend is not None:
            return self._json(200, state.search_backend(body))
        provider = str(body.get("provider") or "")
        query = str(body.get("query") or "").strip().lower()
        models = list(state.models.get(provider, []))
        if state.official_query_filter and query:
            models = [m for m in models if query in m.lower()]
        self._json(200, {"models": sorted(models, key=str.lower), "provider": provider, "source": state.search_source, "error": state.search_error})

    def _discover(self, body: dict):
        state = self.state
        if state.discovery_delay:
            threading.Event().wait(state.discovery_delay)
        if state.discovery_mode == "hang":
            state.release.wait(timeout=30)
        if state.discovery_status != 200:
            return self._send(state.discovery_status, b"discovery unavailable", "text/plain")
        if state.discovery_service is None:
            return self._send(404, b"no discovery service", "text/plain")
        try:
            self._json(200, state.discovery_service(body))
        except Exception as error:  # noqa: BLE001 - surfaced to the test through the 500
            self._send(500, repr(error).encode(), "text/plain")

    def _plugins(self, body: dict):
        state = self.state
        action = body.get("action")
        name = body.get("plugin_name")
        if action == "get_config":
            if name in state.configs:
                return self._json(200, {"ok": True, "data": state.configs[name]})
            return self._send(500, b"TypeError: no config yet", "text/plain")
        if action == "save_config":
            state.configs[name] = body.get("settings") or {}
            return self._json(200, {"ok": True})
        self._json(200, {"ok": False})


class HarnessServer:
    def __init__(self, host: str):
        self.state = HarnessState(host)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.state = self.state  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def start(self) -> "HarnessServer":
        self.thread.start()
        return self

    def stop(self):
        self.state.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":  # manual use: python -m tests.dom.server v2.14
    import sys

    server = HarnessServer(sys.argv[1] if len(sys.argv) > 1 else "v2.14").start()
    print(f"{server.url}/harness.html?host={server.state.host}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()
