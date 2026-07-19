from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from helpers import files

SAVE_DIR = Path(files.get_abs_path("usr", "browser_sessions"))
PLUGIN_DIR = Path(files.get_abs_path("usr", "plugins", "browser_session_sync"))
CONFIG_PATH = PLUGIN_DIR / "config.json"
MANIFEST_FILE_NAME = "_browser_session_sync_state.json"
RESTORED_FLAG = "_browser_session_sync_restored"
RESTORING_FLAG = "_browser_session_sync_restoring"
LISTENERS_FLAG = "_browser_session_sync_listeners"
PAGE_LISTENERS_FLAG = "_browser_session_sync_page_listeners"
SAVE_HANDLE_ATTR = "_browser_session_sync_save_handle"
SAVE_SIGNATURE_ATTR = "_browser_session_sync_save_signature"
SAVE_LAST_AT_ATTR = "_browser_session_sync_save_last_at"
SAVE_DEBOUNCE_SECONDS = 1.5
SAVE_CLOSE_DEBOUNCE_SECONDS = 0.25
SAVE_MIN_INTERVAL_SECONDS = 5.0
SAVE_REFRESH_INTERVAL_SECONDS = 60.0
RESTORE_FAILURE_RETRY_SECONDS = 30.0
DEFAULT_CONFIG = {
    "auto_restore": True,
    "auto_save": True,
    "session_scope": "global",
    "delete_on_chat_remove": True,
    "max_auto_restore_tabs": 0,
    "max_saved_sessions": 500,
    "max_cache_mb": 1024,
}
CONFIG_LIMITS = {
    "max_auto_restore_tabs": (0, 100),
    "max_saved_sessions": (1, 5000),
    "max_cache_mb": (1, 102400),
}


class NoSnapshotChange(RuntimeError):
    pass


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    try:
        from helpers import plugins

        raw = plugins.get_plugin_config("browser_session_sync", agent=None) or {}
    except Exception:
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key != "enabled":
                config[key] = value
    return normalize_config(config, preserve_unknown=True)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def config_bool(name: str, default: bool = True) -> bool:
    return _coerce_bool(load_config().get(name, default), default)


def _coerce_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        coerced = int(float(value))
    except (TypeError, ValueError):
        coerced = default
    return max(minimum, min(maximum, coerced))


def _coerce_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        coerced = default
    return max(minimum, min(maximum, coerced))


def normalize_config(config: dict[str, Any], *, preserve_unknown: bool = False) -> dict[str, Any]:
    normalized = dict(config) if preserve_unknown else {}
    for key, default in DEFAULT_CONFIG.items():
        if isinstance(default, bool):
            normalized[key] = _coerce_bool(config.get(key), default)
        elif key in CONFIG_LIMITS:
            minimum, maximum = CONFIG_LIMITS[key]
            if isinstance(default, float):
                normalized[key] = _coerce_float(config.get(key), default, minimum=minimum, maximum=maximum)
            else:
                normalized[key] = _coerce_int(config.get(key), default, minimum=int(minimum), maximum=int(maximum))
        else:
            normalized[key] = config.get(key, default)
    scope = str(normalized.get("session_scope") or DEFAULT_CONFIG["session_scope"]).strip().lower()
    normalized["session_scope"] = scope if scope in {"global", "chat"} else DEFAULT_CONFIG["session_scope"]
    if "session_scope" not in config and _coerce_bool(config.get("allow_global_fallback"), False):
        normalized["session_scope"] = "global"
    normalized.pop("enabled", None)
    normalized.pop("allow_global_fallback", None)
    return normalized


def plugin_enabled() -> bool:
    return True


def auto_restore_enabled() -> bool:
    return config_bool("auto_restore", True)


def auto_save_enabled() -> bool:
    return config_bool("auto_save", True)


def allow_global_fallback_enabled() -> bool:
    return session_scope() == "global"


def session_scope() -> str:
    return str(load_config().get("session_scope") or "global")


def delete_on_chat_remove_enabled() -> bool:
    return config_bool("delete_on_chat_remove", True)


def max_auto_restore_tabs() -> int:
    config = load_config()
    minimum, maximum = CONFIG_LIMITS["max_auto_restore_tabs"]
    return _coerce_int(config.get("max_auto_restore_tabs"), 0, minimum=minimum, maximum=maximum)


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    config = normalize_config(load_config(), preserve_unknown=True)
    for key in DEFAULT_CONFIG:
        if key in updates:
            config[key] = updates[key]
    config = normalize_config(config, preserve_unknown=True)
    try:
        from helpers import plugins

        plugins.save_plugin_config("browser_session_sync", "", "", config)
    except Exception:
        PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
    enforce_retention(config)
    return config


def boot_id() -> str:
    try:
        stat = Path("/proc/1/stat").read_text(encoding="utf-8").split()
        start_ticks = stat[21] if len(stat) > 21 else ""
        if start_ticks:
            return f"{os.uname().nodename}:{start_ticks}"
    except Exception:
        pass
    return f"{os.uname().nodename}:{int(time.time() // 86400)}"


def context_id_from_extension_data(data: dict[str, Any] | None) -> str:
    args = (data or {}).get("args", ())
    if not isinstance(args, (tuple, list)) or not args:
        return ""
    first = args[0]
    if isinstance(first, str):
        return first.strip()
    return str(getattr(first, "id", "") or "").strip()


def load_snapshot(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "context_state" in raw:
        context_state = raw.get("context_state") or {}
        tabs = raw.get("tabs") or []
    else:
        context_state = raw
        tabs = raw.get("tabs") or []
    return {
        "context_state": context_state,
        "tabs": [tab for tab in tabs if isinstance(tab, dict)],
        "saved_at": raw.get("saved_at") or path.stat().st_mtime,
        "tab_count": int(raw.get("tab_count") or len(tabs)),
        "source": path.name,
    }


def _safe_candidates() -> list[Path]:
    if not SAVE_DIR.exists():
        return []
    return sorted(
        [
            item
            for item in SAVE_DIR.glob("*.json")
            if item.name != MANIFEST_FILE_NAME and item.name.endswith(".json")
        ],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def _session_files() -> list[Path]:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    return [
        path
        for path in SAVE_DIR.glob("*.json")
        if path.name != MANIFEST_FILE_NAME and path.is_file()
    ]


def _manifest_path() -> Path:
    return SAVE_DIR / MANIFEST_FILE_NAME


def load_manifest() -> dict[str, Any]:
    path = _manifest_path()
    if not path.exists():
        return {"version": 2, "contexts": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 2, "contexts": {}}
    if not isinstance(raw, dict):
        return {"version": 2, "contexts": {}}
    raw.setdefault("version", 2)
    raw.setdefault("contexts", {})
    return raw


def save_manifest(manifest: dict[str, Any]) -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    target = _manifest_path()
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    tmp.replace(target)


def _entry_filename(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    filename = str(entry.get("filename") or "").strip()
    if Path(filename).name != filename:
        return ""
    return filename


def repair_manifest() -> dict[str, Any]:
    manifest = load_manifest()
    contexts = manifest.get("contexts")
    if not isinstance(contexts, dict):
        contexts = {}
        manifest["contexts"] = contexts

    changed = False
    for context_id, entry in list(contexts.items()):
        filename = _entry_filename(entry)
        if not filename or not (SAVE_DIR / filename).exists():
            contexts.pop(context_id, None)
            changed = True

    global_entry = manifest.get("global_latest")
    global_filename = _entry_filename(global_entry)
    if global_filename and (SAVE_DIR / global_filename).exists():
        if changed:
            save_manifest(manifest)
        return manifest

    newest_context_id = ""
    newest_entry: dict[str, Any] | None = None
    newest_time = -1.0
    for context_id, entry in contexts.items():
        if not isinstance(entry, dict):
            continue
        updated_at = float(entry.get("updated_at") or 0)
        if updated_at > newest_time:
            newest_context_id = str(context_id)
            newest_entry = entry
            newest_time = updated_at

    if newest_entry:
        manifest["global_latest"] = {"context_id": newest_context_id, **newest_entry}
    else:
        manifest.pop("global_latest", None)
    save_manifest(manifest)
    return manifest


def enforce_retention(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = normalize_config(config or load_config(), preserve_unknown=True)
    max_count = _coerce_int(
        config.get("max_saved_sessions"),
        DEFAULT_CONFIG["max_saved_sessions"],
        minimum=CONFIG_LIMITS["max_saved_sessions"][0],
        maximum=CONFIG_LIMITS["max_saved_sessions"][1],
    )
    max_bytes = int(
        _coerce_float(
            config.get("max_cache_mb"),
            DEFAULT_CONFIG["max_cache_mb"],
            minimum=CONFIG_LIMITS["max_cache_mb"][0],
            maximum=CONFIG_LIMITS["max_cache_mb"][1],
        )
        * 1024
        * 1024
    )

    files = sorted(_session_files(), key=lambda path: path.stat().st_mtime, reverse=True)
    total_size = sum(path.stat().st_size for path in files)
    deleted: list[str] = []

    while files and (len(files) > max_count or total_size > max_bytes):
        victim = files.pop()
        try:
            size = victim.stat().st_size
            victim.unlink()
            total_size -= size
            deleted.append(victim.name)
        except FileNotFoundError:
            pass
        except OSError:
            break

    repair_manifest()
    return {
        "ok": True,
        "deleted": len(deleted),
        "deleted_files": deleted,
        "total_files": len(_session_files()),
        "total_size": sum(path.stat().st_size for path in _session_files()),
        "max_saved_sessions": max_count,
        "max_cache_mb": config["max_cache_mb"],
    }


def delete_session_file(filename: str) -> bool:
    if not filename or Path(filename).name != filename or filename == MANIFEST_FILE_NAME:
        return False
    target = SAVE_DIR / filename
    if not target.exists() or not target.is_file():
        return False
    target.unlink()
    repair_manifest()
    return True


def delete_context_snapshots(context_id: str) -> int:
    context_id = str(context_id or "").strip()
    if not context_id:
        return 0
    manifest = load_manifest()
    global_latest = manifest.get("global_latest")
    protected_global = _entry_filename(global_latest)
    deleted = 0
    for path in _session_files():
        if protected_global and path.name == protected_global:
            continue
        if path.name == f"{context_id}.json" or path.name.startswith(f"{context_id}_"):
            try:
                path.unlink()
                deleted += 1
            except OSError:
                pass
    contexts = manifest.setdefault("contexts", {})
    if isinstance(contexts, dict):
        contexts.pop(context_id, None)
    save_manifest(manifest)
    repair_manifest()
    return deleted


def _manifest_snapshot(context_id: str, *, include_global: bool = True) -> tuple[Path, dict[str, Any]] | None:
    manifest = load_manifest()
    contexts = manifest.get("contexts") if isinstance(manifest.get("contexts"), dict) else {}
    entries = []
    if context_id and isinstance(contexts.get(context_id), dict):
        entries.append(contexts[context_id])
    if include_global:
        global_latest = manifest.get("global_latest")
        if isinstance(global_latest, dict):
            entries.append(global_latest)

    for entry in entries:
        filename = str(entry.get("filename") or "").strip()
        if not filename or Path(filename).name != filename:
            continue
        path = SAVE_DIR / filename
        if not path.exists() or not path.is_file():
            continue
        try:
            return path, load_snapshot(path)
        except Exception:
            continue
    return None


def update_manifest(context_id: str, path: Path, snapshot: dict[str, Any], signature: str) -> None:
    manifest = load_manifest()
    contexts = manifest.setdefault("contexts", {})
    now = float(snapshot.get("saved_at") or time.time())
    entry = {
        "filename": path.name,
        "updated_at": now,
        "tab_count": int(snapshot.get("tab_count") or len(snapshot.get("tabs") or [])),
        "signature": signature,
    }
    context_id = str(context_id or "default")
    contexts[context_id] = entry
    manifest["global_latest"] = {"context_id": context_id, **entry}
    save_manifest(manifest)


def _context_manifest_entry(manifest: dict[str, Any], context_id: str) -> dict[str, Any]:
    contexts = manifest.setdefault("contexts", {})
    context_id = str(context_id or "default")
    entry = contexts.get(context_id)
    if not isinstance(entry, dict):
        entry = {}
        contexts[context_id] = entry
    return entry


def restore_status(context_id: str) -> dict[str, Any]:
    manifest = load_manifest()
    entry = _context_manifest_entry(manifest, context_id)
    return dict(entry.get("restore") or {})


def should_auto_restore(context_id: str) -> tuple[bool, str]:
    if not auto_restore_enabled():
        return False, "Browser session auto-restore is disabled."
    current_boot = boot_id()
    status = restore_status(context_id)
    if status.get("consumed_boot_id") == current_boot:
        return False, "Browser session auto-restore already ran for this boot."
    retry_after = float(status.get("retry_after") or 0)
    if retry_after and time.time() < retry_after:
        return False, "Browser session auto-restore is waiting after a recent failure."
    return True, ""


def mark_restore_attempt(context_id: str, *, state: str, message: str = "", retry: bool = False) -> None:
    manifest = load_manifest()
    entry = _context_manifest_entry(manifest, context_id)
    restore = dict(entry.get("restore") or {})
    restore.update(
        {
            "consumed_boot_id": boot_id(),
            "state": state,
            "message": message,
            "updated_at": time.time(),
        }
    )
    if retry:
        restore["retry_after"] = time.time() + RESTORE_FAILURE_RETRY_SECONDS
    else:
        restore.pop("retry_after", None)
    entry["restore"] = restore
    save_manifest(manifest)


def select_best_snapshot(
    context_id: str,
    filename: str | None = None,
    *,
    allow_global_fallback: bool | None = None,
    scope: str | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    if filename:
        requested = SAVE_DIR / filename
        if requested.name != MANIFEST_FILE_NAME and requested.exists() and requested.is_file():
            return requested, load_snapshot(requested)
        return None

    context_id = str(context_id or "").strip()
    selected_scope = str(scope or session_scope()).strip().lower()
    if selected_scope not in {"global", "chat"}:
        selected_scope = "global"

    if selected_scope == "global":
        global_current = _global_manifest_snapshot()
        if global_current:
            return global_current
        candidates = _safe_candidates()
        for path in candidates:
            try:
                return path, load_snapshot(path)
            except Exception:
                continue
        return None

    current = _manifest_snapshot(context_id, include_global=False)
    if current:
        return current

    candidates = _safe_candidates()
    exact: list[tuple[Path, dict[str, Any]]] = []
    for path in candidates:
        try:
            snapshot = load_snapshot(path)
        except Exception:
            continue
        item = (path, snapshot)
        if context_id and (path.name == f"{context_id}.json" or path.name.startswith(f"{context_id}_")):
            exact.append(item)

    if exact:
        return exact[0]

    use_global_fallback = (
        allow_global_fallback
        if allow_global_fallback is not None
        else False
    )
    if use_global_fallback:
        global_current = _global_manifest_snapshot()
        if global_current:
            return global_current
    return None


def _global_manifest_snapshot() -> tuple[Path, dict[str, Any]] | None:
    manifest = load_manifest()
    global_latest = manifest.get("global_latest")
    filename = str(global_latest.get("filename") or "").strip() if isinstance(global_latest, dict) else ""
    if not filename or Path(filename).name != filename:
        return None
    path = SAVE_DIR / filename
    if not path.exists() or not path.is_file():
        return None
    try:
        return path, load_snapshot(path)
    except Exception:
        return None


def _origin_for_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return ""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def capture_snapshot(core: Any) -> dict[str, Any]:
    context_state = await core.context.storage_state()
    tabs = []
    for browser_id in sorted(getattr(core, "pages", {}) or {}):
        browser_page = core.pages[browser_id]
        page = browser_page.page
        url = str(getattr(page, "url", "") or "")
        if not url or url == "about:blank":
            continue
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass
        tabs.append({"url": url, "title": title, "origin": _origin_for_url(url)})
    return {
        "context_state": context_state,
        "tabs": tabs,
        "saved_at": time.time(),
        "tab_count": len(tabs),
    }


def snapshot_signature(core: Any) -> str:
    urls = []
    for browser_id in sorted(getattr(core, "pages", {}) or {}):
        browser_page = core.pages[browser_id]
        page = browser_page.page
        url = str(getattr(page, "url", "") or "")
        if not url or url == "about:blank":
            continue
        urls.append(url)
    return json.dumps(urls, separators=(",", ":"))


async def save_core_snapshot(core: Any, *, suffix: str | None = None, force: bool = False) -> Path:
    if getattr(core, "_closing", False) or not getattr(core, "context", None):
        raise RuntimeError("Browser runtime is closing.")
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    context_id = str(getattr(core, "context_id", "") or "default")
    signature = snapshot_signature(core)
    now = time.time()
    last_signature = getattr(core, SAVE_SIGNATURE_ATTR, None)
    last_saved_at = float(getattr(core, SAVE_LAST_AT_ATTR, 0) or 0)
    if (
        not force
        and last_signature == signature
        and last_saved_at
        and now - last_saved_at < SAVE_REFRESH_INTERVAL_SECONDS
    ):
        raise NoSnapshotChange("Browser session snapshot has not changed.")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{context_id}_{suffix or timestamp}.json"
    target = SAVE_DIR / filename
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = await capture_snapshot(core)
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(target)
    setattr(core, SAVE_SIGNATURE_ATTR, signature)
    setattr(core, SAVE_LAST_AT_ATTR, now)
    update_manifest(context_id, target, payload, signature)
    enforce_retention()
    return target


def schedule_save(core: Any, *, delay: float | None = None, reason: str = "") -> None:
    if not auto_save_enabled():
        return
    if not getattr(core, "context", None):
        return
    if getattr(core, "_closing", False):
        return
    if getattr(core, RESTORING_FLAG, False):
        return
    is_close = reason == "close"
    requested_delay = SAVE_CLOSE_DEBOUNCE_SECONDS if is_close else SAVE_DEBOUNCE_SECONDS
    if delay is not None:
        requested_delay = float(delay)
    if not is_close:
        last_saved_at = float(getattr(core, SAVE_LAST_AT_ATTR, 0) or 0)
        remaining = SAVE_MIN_INTERVAL_SECONDS - (time.time() - last_saved_at)
        if remaining > requested_delay:
            requested_delay = remaining
    old_handle = getattr(core, SAVE_HANDLE_ATTR, None)
    if old_handle and not old_handle.cancelled():
        old_handle.cancel()
    loop = asyncio.get_running_loop()

    async def _safe_save() -> None:
        try:
            await save_core_snapshot(core, force=is_close)
        except NoSnapshotChange:
            pass
        except Exception:
            pass

    def _run() -> None:
        if getattr(core, "_closing", False) or not getattr(core, "context", None):
            return
        asyncio.create_task(_safe_save())

    setattr(core, SAVE_HANDLE_ATTR, loop.call_later(max(0.0, requested_delay), _run))


def _register_page_save_listeners(core: Any, page: Any) -> None:
    if getattr(page, PAGE_LISTENERS_FLAG, False):
        return
    setattr(page, PAGE_LISTENERS_FLAG, True)

    def _save_from_load(*_args: Any) -> None:
        schedule_save(core, reason="load")

    def _save_from_close(*_args: Any) -> None:
        schedule_save(core, reason="close")

    page.on("load", _save_from_load)
    page.on("close", _save_from_close)


def register_auto_save(core: Any) -> None:
    if not auto_save_enabled():
        return
    if not getattr(core, "context", None):
        return
    if getattr(core, LISTENERS_FLAG, False):
        return
    setattr(core, LISTENERS_FLAG, True)

    def _on_page(page: Any) -> None:
        _register_page_save_listeners(core, page)
        schedule_save(core, reason="page")

    core.context.on("page", _on_page)
    for browser_page in list((getattr(core, "pages", {}) or {}).values()):
        _register_page_save_listeners(core, browser_page.page)


async def _inject_storage(core: Any, context_state: dict[str, Any]) -> None:
    cookies = context_state.get("cookies") or []
    if cookies:
        await core.context.add_cookies(cookies)

    origins = [
        origin
        for origin in (context_state.get("origins") or [])
        if origin.get("origin") and origin.get("localStorage")
    ]
    if not origins:
        return
    init_js = (
        "(() => {"
        f"const DATA = {json.dumps({'origins': origins})};"
        "const origin = window.location.origin;"
        "for (const entry of DATA.origins) {"
        " if (entry.origin === origin) {"
        "  for (const item of (entry.localStorage || [])) {"
        "   try { localStorage.setItem(item.name, item.value); } catch(e) {}"
        "  }"
        "  break;"
        " }"
        "}"
        "})();"
    )
    await core.context.add_init_script(script=init_js)


async def restore_core_session(
    core: Any,
    *,
    filename: str | None = None,
    force: bool = False,
) -> str:
    if not force and not auto_restore_enabled():
        return "Browser session auto-restore is disabled."
    register_auto_save(core)
    if not force and getattr(core, RESTORED_FLAG, False):
        return "Browser session restore already ran for this runtime."
    setattr(core, RESTORED_FLAG, True)

    selected = select_best_snapshot(
        str(getattr(core, "context_id", "") or ""),
        filename,
        allow_global_fallback=force or None,
    )
    if not selected:
        return "No saved browser sessions found."
    path, snapshot = selected
    context_state = snapshot.get("context_state") or {}
    tabs = snapshot.get("tabs") or []

    setattr(core, RESTORING_FLAG, True)
    try:
        existing_urls = {
            str(browser_page.page.url or "")
            for browser_page in (getattr(core, "pages", {}) or {}).values()
        }
        state = await core.context.storage_state()
        if force or not state.get("cookies"):
            await _inject_storage(core, context_state)

        opened = 0
        first_restored_browser_id: int | None = None
        native_max_tabs = core._max_open_tabs()
        restore_limit = max_auto_restore_tabs()
        max_tabs = native_max_tabs
        if not force and restore_limit > 0:
            max_tabs = min(native_max_tabs, restore_limit)
        for tab in tabs[:max_tabs]:
            url = str(tab.get("url") or "").strip()
            if not url or url == "about:blank" or url in existing_urls:
                continue
            core._ensure_can_open_page()
            page = await core.context.new_page()
            browser_page = await core._register_page(page)
            _register_page_save_listeners(core, page)
            if first_restored_browser_id is None:
                first_restored_browser_id = browser_page.id
            await core._goto(page, url)
            existing_urls.add(url)
            opened += 1
        if first_restored_browser_id is not None:
            core.last_interacted_browser_id = first_restored_browser_id
    finally:
        setattr(core, RESTORING_FLAG, False)

    if opened or force:
        schedule_save(core, delay=SAVE_CLOSE_DEBOUNCE_SECONDS, reason="close")
    return f"Restored {opened} tabs from {path.name}."


async def auto_restore_core_session(core: Any) -> str:
    """Restore directly inside the native browser worker during runtime startup."""
    context_id = str(getattr(core, "context_id", "") or "").strip()
    if not context_id:
        return "Browser session auto-restore skipped: browser context is unavailable."

    ok, reason = should_auto_restore(context_id)
    if not ok:
        return reason

    mark_restore_attempt(context_id, state="started", message="Auto-restore started.")
    try:
        message = await restore_core_session(core, force=False)
    except Exception as exc:
        message = f"Browser session auto-restore failed: {exc}"
        mark_restore_attempt(context_id, state="failed", message=message, retry=True)
        raise

    mark_restore_attempt(context_id, state="done", message=message)
    return message


async def _run_with_core(context_id: str, callback: Any, *, create: bool = False) -> str:
    return await _run_with_core_started(context_id, callback, create=create, ensure_started=False)


async def _run_with_core_started(
    context_id: str,
    callback: Any,
    *,
    create: bool = False,
    ensure_started: bool = False,
) -> str:
    from plugins._browser.helpers.runtime import get_runtime

    runtime = await get_runtime(context_id, create=create)
    if not runtime:
        return "No active browser runtime. Open Browser first."

    async def runner() -> str:
        if ensure_started:
            await runtime._core.ensure_started()
        return await callback(runtime._core)

    return await runtime._worker.execute_inside(runner)


async def save_runtime_snapshot_for_context(context_id: str) -> str:
    async def callback(core: Any) -> str:
        path = await save_core_snapshot(core, force=True)
        snapshot = load_snapshot(path)
        state = snapshot.get("context_state") or {}
        return (
            f"Saved {len(snapshot.get('tabs') or [])} tabs, "
            f"{len(state.get('cookies') or [])} cookies, and "
            f"{len(state.get('origins') or [])} origins to {path.name}"
        )

    return await _run_with_core_started(context_id, callback, create=False, ensure_started=False)


def save_runtime_snapshot_for_context_sync(context_id: str, *, timeout: float = 8.0) -> str:
    try:
        from helpers.defer import DeferredTask
    except Exception:
        return "Browser session sync save skipped: DeferredTask unavailable."
    try:
        task = DeferredTask().start_task(save_runtime_snapshot_for_context, context_id)
        return str(task.result_sync(timeout=timeout))
    except Exception as exc:
        return f"Browser session sync save skipped: {exc}"


def handle_context_reset_sync(context_id: str) -> None:
    if context_id and auto_save_enabled():
        save_runtime_snapshot_for_context_sync(context_id)


def handle_context_remove_sync(context_id: str) -> None:
    if not context_id:
        return
    if delete_on_chat_remove_enabled():
        delete_context_snapshots(context_id)
    elif auto_save_enabled():
        save_runtime_snapshot_for_context_sync(context_id)


async def restore_runtime_session_for_context(
    context_id: str,
    filename: str | None = None,
    *,
    force: bool = False,
) -> str:
    async def callback(core: Any) -> str:
        return await restore_core_session(core, filename=filename, force=force)

    return await _run_with_core_started(context_id, callback, create=False, ensure_started=True)


async def auto_restore_runtime_session_for_context(context_id: str) -> str:
    ok, reason = should_auto_restore(context_id)
    if not ok:
        return reason

    async def callback(core: Any) -> str:
        return await auto_restore_core_session(core)

    return await _run_with_core_started(context_id, callback, create=True, ensure_started=True)
