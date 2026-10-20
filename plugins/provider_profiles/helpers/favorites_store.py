"""Server-side model favorites for the Provider Profiles plugin.

One JSON file, shared by every browser of the instance:

    {"schema_version": 1, "rev": 7,
     "types": {"chat": [{"provider", "api_base", "name", "starred_at", "last_used_at"}], ...}}

Design rules
- Operations are idempotent and applied server-side (set on/off, touch), never
  as whole-file replacement, so two tabs cannot clobber each other.
- Every write happens under a lock *file* (module-level locks are not safe: Agent
  Zero purges plugin modules on plugin events) and is atomic (temp file +
  os.replace) with a .bak of the previous version.
- A corrupt file is quarantined (renamed) and the .bak, when valid, is used.
- Identity is (model type, provider, canonical API base, name). The canonical API
  base rules are mirrored in webui/favorites-core.js and pinned by
  tests/vectors/identity_vectors.json.
- No secrets are stored: API bases carrying credentials or query strings are rejected.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
MODEL_TYPES = ("chat", "vision", "utility", "embedding")
MAX_PER_TYPE = 1000
MAX_NAME = 512
MAX_BASE = 512
LOCK_STALE_SECONDS = 10.0
LOCK_TIMEOUT_SECONDS = 3.0

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_.:\-]{0,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DEFAULT_PORTS = {"http": 80, "https": 443}


class FavoritesError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


# ---------------------------------------------------------------- identity


def canonical_base(api_base: Any) -> str:
    """Canonical form of an API base URL used for favorite identity ('' = provider default)."""
    text = str(api_base or "").strip()
    if not text:
        return ""
    if len(text) > MAX_BASE:
        raise FavoritesError("invalid_api_base", "API base is too long")
    try:
        parts = urlsplit(text)
        host = parts.hostname
        port = parts.port
    except ValueError as error:
        raise FavoritesError("invalid_api_base", str(error)) from error
    if parts.scheme not in ("http", "https") or not host:
        raise FavoritesError("invalid_api_base", "API base must be an http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise FavoritesError("api_base_credentials", "API base must not contain credentials")
    if parts.query or parts.fragment or "?" in text or "#" in text:
        raise FavoritesError("api_base_query", "API base must not contain a query string or fragment")
    host = host.lower()
    if ":" in host:
        host = f"[{host}]"
    else:
        try:
            host = host.encode("idna").decode("ascii")  # same punycode form the browser's URL class produces
        except UnicodeError as error:
            raise FavoritesError("invalid_api_base", "API base host is not valid") from error
    netloc = host if port is None or port == _DEFAULT_PORTS[parts.scheme] else f"{host}:{port}"
    segments: list[str] = []
    for segment in parts.path.split("/"):  # resolve dot segments and empty segments like the JS mirror
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    if segments and segments[-1].lower() == "v1":
        segments.pop()
    path = "/" + "/".join(segments) if segments else ""
    return f"{parts.scheme}://{netloc}{path}"


def clean_entry(model_type: Any, provider: Any, api_base: Any, name: Any) -> dict[str, str]:
    """Validate the four identity fields and return them normalized."""
    model_type = str(model_type or "").strip().lower()
    if model_type not in MODEL_TYPES:
        raise FavoritesError("invalid_model_type", f"model type must be one of {', '.join(MODEL_TYPES)}")
    provider = str(provider or "").strip().lower()
    if not _PROVIDER_RE.match(provider):
        raise FavoritesError("invalid_provider", "provider is missing or has unsupported characters")
    name = str(name or "").strip()
    if not name or len(name) > MAX_NAME or _CONTROL_RE.search(name):
        raise FavoritesError("invalid_name", "model name is empty, too long or contains control characters")
    base_text = str(api_base or "").strip()
    canonical_base(base_text)  # validates
    return {"model_type": model_type, "provider": provider, "api_base": base_text, "name": name}


def identity_of(entry: dict[str, Any], model_type: str | None = None) -> tuple[str, str, str, str]:
    return (
        model_type or str(entry.get("model_type", "")),
        str(entry.get("provider", "")).lower(),
        canonical_base(entry.get("api_base", "")),
        str(entry.get("name", "")),
    )


# ---------------------------------------------------------------- store


def _empty() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "rev": 0, "types": {t: [] for t in MODEL_TYPES}}


def _sanitize(data: Any) -> dict[str, Any] | None:
    """Return a clean copy of loaded data, or None when the shape is unusable."""
    if not isinstance(data, dict) or not isinstance(data.get("types"), dict):
        return None
    clean = _empty()
    rev = data.get("rev")
    clean["rev"] = rev if isinstance(rev, int) and not isinstance(rev, bool) and rev >= 0 else 0
    for model_type in MODEL_TYPES:
        seen: set[tuple[str, str, str, str]] = set()
        items = data["types"].get(model_type, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                entry = clean_entry(model_type, item.get("provider"), item.get("api_base"), item.get("name"))
                ident = identity_of(entry, model_type)
            except FavoritesError:
                continue
            if ident in seen:
                continue
            seen.add(ident)
            starred = item.get("starred_at")
            used = item.get("last_used_at")
            starred = float(starred) if isinstance(starred, (int, float)) and not isinstance(starred, bool) else 0.0
            used = float(used) if isinstance(used, (int, float)) and not isinstance(used, bool) else starred
            clean["types"][model_type].append({
                "provider": entry["provider"],
                "api_base": entry["api_base"],
                "name": entry["name"],
                "starred_at": starred,
                "last_used_at": used,
            })
    return clean


def _recency_key(item: dict[str, Any]):
    return (-item["last_used_at"], -item["starred_at"], item["name"].lower(), item["provider"])


class FavoritesStore:
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        clock: Callable[[], float] = time.time,
        max_per_type: int = MAX_PER_TYPE,
        lock_timeout: float = LOCK_TIMEOUT_SECONDS,
        lock_stale: float = LOCK_STALE_SECONDS,
    ):
        self.path = Path(path)
        self.bak_path = self.path.with_name(self.path.name + ".bak")
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.clock = clock
        self.max_per_type = max_per_type
        self.lock_timeout = lock_timeout
        self.lock_stale = lock_stale

    # -- locking
    def _lock_identity(self) -> tuple[int, int, float] | None:
        """(inode, mtime_ns, mtime) of the lock file via stat only (never open it: on Windows a reader blocks the owner's unlink)."""
        try:
            info = self.lock_path.stat()
        except OSError:
            return None
        return info.st_ino, info.st_mtime_ns, info.st_mtime

    @contextlib.contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                info = os.fstat(fd)
                os.close(fd)
                mine = (info.st_ino, info.st_mtime_ns)
                break
            except (FileExistsError, PermissionError):
                # PermissionError: on Windows a lock whose deletion is still pending cannot be re-created yet.
                seen = self._lock_identity()
                if seen is None:
                    if time.monotonic() >= deadline:
                        raise FavoritesError("busy", "favorites file is locked by another request")
                    time.sleep(0.002)
                    continue
                if time.time() - seen[2] > self.lock_stale:
                    again = self._lock_identity()
                    if again is not None and again[:2] == seen[:2]:
                        # Remove only the very lock judged stale (re-checked just before), never a fresh one.
                        self._remove_lock()
                    continue
                if time.monotonic() >= deadline:
                    raise FavoritesError("busy", "favorites file is locked by another request")
                time.sleep(0.005)
        try:
            yield
        finally:
            current = self._lock_identity()
            if current is not None and current[:2] == mine:  # never delete a lock someone else took over
                self._remove_lock()

    def _remove_lock(self) -> None:
        for _ in range(20):  # Windows can briefly refuse to delete a file another thread just stat-ed
            try:
                self.lock_path.unlink()
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.005)

    # -- file io
    def _load_file(self, path: Path) -> tuple[str, dict[str, Any] | None]:
        """Return ("ok", data), ("missing", None) or ("invalid", None). Transient OS errors are retried and then
        raised: they must never be mistaken for corruption (Windows refuses reads while a replace is in flight)."""
        for attempt in range(40):
            try:
                raw = path.read_text(encoding="utf-8")
                break
            except FileNotFoundError:
                return "missing", None
            except OSError:
                if attempt == 39:
                    raise
                time.sleep(0.005)
        try:
            data = _sanitize(json.loads(raw))
        except ValueError:
            return "invalid", None
        return ("ok", data) if data is not None else ("invalid", None)

    def _read(self) -> dict[str, Any]:
        status, data = self._load_file(self.path)
        if status == "ok":
            return data
        if status == "invalid":
            self._quarantine()
        backup_status, backup = self._load_file(self.bak_path)
        return backup if backup_status == "ok" else _empty()

    def _quarantine(self) -> None:
        target = self.path.with_name(f"{self.path.name}.corrupt-{int(self.clock())}")
        with contextlib.suppress(OSError):
            os.replace(self.path, target)

    def _write(self, data: dict[str, Any]) -> None:
        data["rev"] = int(data.get("rev", 0)) + 1
        for model_type in MODEL_TYPES:
            data["types"][model_type].sort(key=_recency_key)
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                with contextlib.suppress(OSError):
                    self.bak_path.write_bytes(self.path.read_bytes())  # previous good version
            for attempt in range(40):  # Windows: replace fails while another thread is reading the file
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt == 39:
                        raise
                    time.sleep(0.005)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()

    # -- public api
    def snapshot(self) -> dict[str, Any]:
        data = self._read()
        for model_type in MODEL_TYPES:
            data["types"][model_type].sort(key=_recency_key)
        return data

    def set_favorite(self, model_type: Any, provider: Any, api_base: Any, name: Any, on: bool) -> dict[str, Any]:
        entry = clean_entry(model_type, provider, api_base, name)
        ident = identity_of(entry)
        model_type = entry["model_type"]
        with self._locked():
            data = self._read()
            items = data["types"][model_type]
            index = next((i for i, item in enumerate(items) if identity_of(item, model_type) == ident), None)
            if on:
                if index is None:
                    if len(items) >= self.max_per_type:
                        raise FavoritesError("limit_reached", f"limit of {self.max_per_type} favorites for {model_type} reached")
                    now = float(self.clock())
                    items.append({
                        "provider": entry["provider"], "api_base": entry["api_base"], "name": entry["name"],
                        "starred_at": now, "last_used_at": now,
                    })
                    self._write(data)
                # already starred: idempotent, no write
            elif index is not None:
                del items[index]
                self._write(data)
            starred = on
        return {"starred": starred, "snapshot": self.snapshot()}

    def touch(self, model_type: Any, provider: Any, api_base: Any, name: Any) -> dict[str, Any]:
        entry = clean_entry(model_type, provider, api_base, name)
        ident = identity_of(entry)
        model_type = entry["model_type"]
        with self._locked():
            data = self._read()
            touched = False
            for item in data["types"][model_type]:
                if identity_of(item, model_type) == ident:
                    item["last_used_at"] = max(float(self.clock()), item["last_used_at"])
                    touched = True
                    break
            if touched:
                self._write(data)
        return {"touched": touched, "snapshot": self.snapshot()}


# ---------------------------------------------------------------- request dispatch


def _fail(error: FavoritesError) -> dict[str, Any]:
    return {"ok": False, "error": error.code, "message": error.message}


def handle(payload: Any, store: FavoritesStore, settings: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one API request. Always returns a JSON-serializable dict."""
    if not isinstance(payload, dict):
        return _fail(FavoritesError("invalid_request", "request body must be an object"))
    action = str(payload.get("action") or "bootstrap")
    try:
        if action == "settings":
            return {"ok": True, "settings": settings}
        if action in ("bootstrap", "list"):
            snap = store.snapshot()
            result = {"ok": True, "rev": snap["rev"], "types": snap["types"]}
            if action == "bootstrap":
                result["settings"] = settings
            return result
        if action == "set":
            on = payload.get("on")
            if not isinstance(on, bool):
                raise FavoritesError("invalid_request", "'on' must be true or false")
            result = store.set_favorite(payload.get("model_type"), payload.get("provider"), payload.get("api_base"), payload.get("name"), on)
        elif action == "touch":
            result = store.touch(payload.get("model_type"), payload.get("provider"), payload.get("api_base"), payload.get("name"))
        else:
            raise FavoritesError("unknown_action", f"unknown action {action!r}")
        snap = result.pop("snapshot")
        return {"ok": True, **result, "rev": snap["rev"], "types": snap["types"]}
    except FavoritesError as error:
        return _fail(error)
    except OSError as error:
        return _fail(FavoritesError("storage_error", f"favorites storage failed: {error.__class__.__name__}"))
