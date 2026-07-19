from __future__ import annotations

import asyncio
import json
import os
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from usr.plugins.browser_session_sync.helpers import session_sync


class FakePage:
    def __init__(self, url: str = "about:blank", title: str = ""):
        self.url = url
        self._title = title
        self.listeners = {}
        self.goto_calls = []

    def on(self, event: str, callback):
        self.listeners[event] = callback

    async def title(self):
        return self._title

    async def goto(self, url: str, **kwargs):
        self.url = url
        self.goto_calls.append((url, kwargs))


class FakeContext:
    def __init__(self):
        self.listeners = {}
        self.pages = []
        self.cookies = []
        self.origins = []
        self.added_cookies = []
        self.init_scripts = []

    def on(self, event: str, callback):
        self.listeners[event] = callback

    async def storage_state(self):
        return {"cookies": list(self.cookies), "origins": list(self.origins)}

    async def add_cookies(self, cookies):
        self.added_cookies.extend(cookies)
        self.cookies.extend(cookies)

    async def add_init_script(self, **kwargs):
        self.init_scripts.append(kwargs)

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        if "page" in self.listeners:
            self.listeners["page"](page)
        return page


class FakeCore:
    def __init__(self, context_id: str = "ctx"):
        self.context_id = context_id
        self.context = FakeContext()
        self.pages = {}
        self.last_interacted_browser_id = None
        self.next_id = 1
        self.started = False

    def _max_open_tabs(self):
        return 8

    def _ensure_can_open_page(self):
        if len(self.pages) >= self._max_open_tabs():
            raise RuntimeError("too many tabs")

    async def _register_page(self, page):
        item = SimpleNamespace(id=self.next_id, page=page)
        self.pages[self.next_id] = item
        self.next_id += 1
        return item

    async def _goto(self, page, url):
        await page.goto(url)

    async def ensure_started(self):
        self.started = True


def write_snapshot(path: Path, payload: dict):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_context_id_from_extension_data_accepts_context_object():
    data = {"args": (SimpleNamespace(id="abc123"),)}

    assert session_sync.context_id_from_extension_data(data) == "abc123"
    assert session_sync.context_id_from_extension_data({"args": ("raw-id",)}) == "raw-id"


def test_select_best_snapshot_prefers_exact_tab_snapshot_in_chat_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    write_snapshot(tmp_path / "ctx_older.json", {"cookies": [{"domain": "example.com"}], "origins": []})
    write_snapshot(
        tmp_path / "other_newer.json",
        {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": "https://other.test"}]},
    )
    write_snapshot(
        tmp_path / "ctx_newer.json",
        {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": "https://ctx.test"}]},
    )

    selected = session_sync.select_best_snapshot("ctx", scope="chat")

    assert selected is not None
    path, snapshot = selected
    assert path.name == "ctx_newer.json"
    assert snapshot["tabs"][0]["url"] == "https://ctx.test"


def test_select_best_snapshot_uses_global_current_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    ctx_path = tmp_path / "ctx_current.json"
    global_path = tmp_path / "other_current.json"
    write_snapshot(
        ctx_path,
        {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": "https://ctx.test"}]},
    )
    write_snapshot(
        global_path,
        {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": "https://other.test"}]},
    )
    session_sync.update_manifest("ctx", ctx_path, session_sync.load_snapshot(ctx_path), '["https://ctx.test"]')
    session_sync.update_manifest("other", global_path, session_sync.load_snapshot(global_path), '["https://other.test"]')

    selected = session_sync.select_best_snapshot("ctx")
    assert selected is not None
    path, snapshot = selected
    assert path.name == "other_current.json"
    assert snapshot["tabs"][0]["url"] == "https://other.test"


def test_select_best_snapshot_chat_scope_preserves_chat_current(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    ctx_path = tmp_path / "ctx_current.json"
    global_path = tmp_path / "other_current.json"
    write_snapshot(
        ctx_path,
        {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": "https://ctx.test"}]},
    )
    write_snapshot(
        global_path,
        {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": "https://other.test"}]},
    )
    session_sync.update_manifest("ctx", ctx_path, session_sync.load_snapshot(ctx_path), '["https://ctx.test"]')
    session_sync.update_manifest("other", global_path, session_sync.load_snapshot(global_path), '["https://other.test"]')

    selected = session_sync.select_best_snapshot("ctx", scope="chat")

    assert selected is not None
    path, snapshot = selected
    assert path.name == "ctx_current.json"
    assert snapshot["tabs"][0]["url"] == "https://ctx.test"


def test_select_best_snapshot_prefers_newest_current_state_over_more_tabs(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    older = tmp_path / "ctx_older_many_tabs.json"
    newer = tmp_path / "ctx_newer_one_tab.json"
    write_snapshot(
        older,
        {
            "context_state": {"cookies": [], "origins": []},
            "tabs": [
                {"url": "https://one.test"},
                {"url": "https://two.test"},
                {"url": "https://three.test"},
            ],
        },
    )
    write_snapshot(
        newer,
        {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": "https://kept.test"}]},
    )
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    session_sync.update_manifest(
        "ctx",
        newer,
        session_sync.load_snapshot(newer),
        '["https://kept.test"]',
    )

    selected = session_sync.select_best_snapshot("ctx", scope="chat")

    assert selected is not None
    path, snapshot = selected
    assert path.name == newer.name
    assert [tab["url"] for tab in snapshot["tabs"]] == ["https://kept.test"]


def test_zero_tab_current_state_beats_older_tab_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    older = tmp_path / "ctx_older_many_tabs.json"
    current = tmp_path / "ctx_current_empty.json"
    write_snapshot(
        older,
        {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": "https://old.test"}]},
    )
    write_snapshot(current, {"context_state": {"cookies": [], "origins": []}, "tabs": [], "tab_count": 0})
    session_sync.update_manifest("ctx", current, session_sync.load_snapshot(current), "[]")

    selected = session_sync.select_best_snapshot("ctx", scope="chat")

    assert selected is not None
    path, snapshot = selected
    assert path.name == current.name
    assert snapshot["tabs"] == []


def test_legacy_snapshot_normalizes_to_context_state(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    write_snapshot(tmp_path / "legacy.json", {"cookies": [{"domain": "example.com"}], "origins": []})

    snapshot = session_sync.load_snapshot(tmp_path / "legacy.json")

    assert snapshot["context_state"]["cookies"][0]["domain"] == "example.com"
    assert snapshot["tabs"] == []


def test_register_auto_save_adds_context_and_page_listeners():
    core = FakeCore()
    page = FakePage("https://example.com")
    core.pages[1] = SimpleNamespace(id=1, page=page)

    session_sync.register_auto_save(core)

    assert "page" in core.context.listeners
    assert "load" in page.listeners
    assert "close" in page.listeners
    assert "framenavigated" not in page.listeners


def test_restore_core_session_is_idempotent_and_opens_saved_tabs(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(session_sync, "schedule_save", lambda *args, **kwargs: None)
    write_snapshot(
        tmp_path / "ctx_20260606_210539.json",
        {
            "context_state": {"cookies": [{"name": "sid", "value": "1", "domain": ".example.com", "path": "/"}], "origins": []},
            "tabs": [{"url": "https://example.com"}, {"url": "https://github.com"}],
        },
    )
    core = FakeCore("ctx")

    first = asyncio.run(session_sync.restore_core_session(core))
    second = asyncio.run(session_sync.restore_core_session(core))

    assert "Restored 2 tabs" in first
    assert "already ran" in second
    assert len(core.pages) == 2
    assert len(core.context.added_cookies) == 1


def test_runtime_start_restore_registers_all_tabs_before_first_listing(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(session_sync, "boot_id", lambda: "boot-1")
    monkeypatch.setattr(session_sync, "schedule_save", lambda *args, **kwargs: None)
    write_snapshot(
        tmp_path / "global_current.json",
        {
            "context_state": {"cookies": [], "origins": []},
            "tabs": [
                {"url": "https://first.test"},
                {"url": "https://second.test"},
                {"url": "https://third.test"},
            ],
        },
    )
    core = FakeCore("ctx")

    message = asyncio.run(session_sync.auto_restore_core_session(core))
    listed_urls = [core.pages[page_id].page.url for page_id in sorted(core.pages)]

    assert "Restored 3 tabs" in message
    assert listed_urls == ["https://first.test", "https://second.test", "https://third.test"]
    assert "about:blank" not in listed_urls
    assert core.last_interacted_browser_id == 1
    assert session_sync.restore_status("ctx")["state"] == "done"
    assert asyncio.run(session_sync.auto_restore_core_session(core)) == (
        "Browser session auto-restore already ran for this boot."
    )


def test_runtime_start_extension_uses_live_core_directly(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    extension_path = root / "extensions/python/browser_runtime_started/_50_restore_session.py"
    extension_spec = importlib.util.spec_from_file_location("browser_runtime_start_restore", extension_path)
    extension_module = importlib.util.module_from_spec(extension_spec)
    assert extension_spec.loader is not None
    extension_spec.loader.exec_module(extension_module)

    calls = []

    async def fake_auto_restore(core):
        calls.append(core)
        return "Restored 2 tabs from current.json."

    monkeypatch.setattr(extension_module, "auto_restore_core_session", fake_auto_restore)
    core = FakeCore("ctx")

    assert asyncio.run(extension_module.BrowserSessionRestoreOnRuntimeStart(agent=None).execute(runtime=core)) is None
    assert calls == [core]


def test_viewer_fallback_is_early_and_cannot_restore_a_consumed_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(session_sync, "boot_id", lambda: "boot-1")
    monkeypatch.setattr(session_sync, "schedule_save", lambda *args, **kwargs: None)
    write_snapshot(
        tmp_path / "ctx_current.json",
        {
            "context_state": {"cookies": [], "origins": []},
            "tabs": [{"url": "https://one.test"}, {"url": "https://two.test"}],
        },
    )
    core = FakeCore("ctx")
    assert "Restored 2 tabs" in asyncio.run(session_sync.auto_restore_core_session(core))

    async def fake_run(context_id, callback, *, create=False, ensure_started=False):
        assert context_id == "ctx"
        assert create is True
        assert ensure_started is True
        return await callback(core)

    monkeypatch.setattr(session_sync, "_run_with_core_started", fake_run)
    message = asyncio.run(session_sync.auto_restore_runtime_session_for_context("ctx"))

    assert message == "Browser session auto-restore already ran for this boot."
    assert len(core.pages) == 2

    root = Path(__file__).resolve().parents[1]
    event_dir = root / "extensions/python/webui_ws_event"
    assert (event_dir / "_40_browser_session_restore.py").exists()
    assert not (event_dir / "_50_browser_session_restore.py").exists()


def test_auto_restore_tab_limit_does_not_limit_saved_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(session_sync, "schedule_save", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        session_sync,
        "load_config",
        lambda: {
            "auto_restore": True,
            "auto_save": True,
            "session_scope": "chat",
            "delete_on_chat_remove": True,
            "max_auto_restore_tabs": 1,
            "max_saved_sessions": 500,
            "max_cache_mb": 1024,
        },
    )
    write_snapshot(
        tmp_path / "ctx_limited.json",
        {
            "context_state": {"cookies": [], "origins": []},
            "tabs": [{"url": "https://one.test"}, {"url": "https://two.test"}],
        },
    )
    core = FakeCore("ctx")

    message = asyncio.run(session_sync.restore_core_session(core))

    assert "Restored 1 tabs" in message
    assert len(core.pages) == 1

    core.pages[2] = SimpleNamespace(id=2, page=FakePage("https://two.test", "Two"))
    saved = asyncio.run(session_sync.save_core_snapshot(core, force=True))
    snapshot = session_sync.load_snapshot(saved)
    assert [tab["url"] for tab in snapshot["tabs"]] == ["https://one.test", "https://two.test"]


def test_schedule_save_coalesces_rapid_events(monkeypatch):
    calls = []
    core = FakeCore("ctx")

    async def fake_save_core_snapshot(core, *, suffix=None, force=False):
        calls.append(force)
        return Path("saved.json")

    monkeypatch.setattr(session_sync, "save_core_snapshot", fake_save_core_snapshot)

    async def run():
        session_sync.schedule_save(core, delay=0.01, reason="load")
        session_sync.schedule_save(core, delay=0.01, reason="load")
        await asyncio.sleep(0.05)

    asyncio.run(run())

    assert calls == [False]


def test_save_core_snapshot_updates_manifest_and_skips_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    core = FakeCore("ctx")
    page = FakePage("https://example.com", "Example")
    core.pages[1] = SimpleNamespace(id=1, page=page)

    saved = asyncio.run(session_sync.save_core_snapshot(core, force=True))
    manifest = session_sync.load_manifest()

    assert saved.exists()
    assert manifest["contexts"]["ctx"]["filename"] == saved.name
    try:
        asyncio.run(session_sync.save_core_snapshot(core))
    except session_sync.NoSnapshotChange:
        pass
    else:
        raise AssertionError("unchanged snapshot should have been skipped")


def test_auto_restore_consumed_once_per_boot(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(session_sync, "boot_id", lambda: "boot-1")
    monkeypatch.setattr(session_sync, "load_config", lambda: {"auto_restore": True, "auto_save": True, "session_scope": "global"})

    calls = []
    core = FakeCore("ctx")

    async def fake_restore_core_session(_core, *, filename=None, force=False):
        return "Restored 1 tabs from ctx_current.json."

    async def fake_run(context_id, callback, *, create=False, ensure_started=False):
        calls.append((context_id, create, ensure_started))
        return await callback(core)

    monkeypatch.setattr(session_sync, "_run_with_core_started", fake_run)
    monkeypatch.setattr(session_sync, "restore_core_session", fake_restore_core_session)

    first = asyncio.run(session_sync.auto_restore_runtime_session_for_context("ctx"))
    second = asyncio.run(session_sync.auto_restore_runtime_session_for_context("ctx"))

    assert "Restored 1 tabs" in first
    assert "already ran" in second
    assert calls == [("ctx", True, True)]


def test_disabled_restore_and_save_settings_block_their_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(session_sync, "load_config", lambda: {"auto_restore": False, "auto_save": False})
    core = FakeCore("ctx")

    assert asyncio.run(session_sync.auto_restore_runtime_session_for_context("ctx")) == "Browser session auto-restore is disabled."
    session_sync.schedule_save(core, delay=0.01)

    assert not getattr(core, session_sync.SAVE_HANDLE_ATTR, None)


def test_save_config_validates_and_removes_legacy_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path / "sessions")
    monkeypatch.setattr(session_sync, "PLUGIN_DIR", tmp_path)
    monkeypatch.setattr(session_sync, "CONFIG_PATH", tmp_path / "config.json")
    session_sync.CONFIG_PATH.write_text(
        json.dumps({"enabled": False, "allow_global_fallback": True, "unknown": "kept", "max_saved_sessions": "bad"}),
        encoding="utf-8",
    )

    config = session_sync.save_config(
        {
            "auto_restore": "false",
            "allow_global_fallback": "true",
            "session_scope": "chat",
            "max_auto_restore_tabs": 999,
            "max_saved_sessions": 0,
            "max_cache_mb": 0,
        }
    )
    persisted = json.loads(session_sync.CONFIG_PATH.read_text(encoding="utf-8"))

    assert "enabled" not in persisted
    assert "allow_global_fallback" not in persisted
    assert config["unknown"] == "kept"
    assert config["auto_restore"] is False
    assert config["session_scope"] == "chat"
    assert config["max_auto_restore_tabs"] == 100
    assert config["max_saved_sessions"] == 1
    assert config["max_cache_mb"] == 1


def test_retention_enforces_count_and_repairs_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    files = []
    for idx in range(3):
        path = tmp_path / f"ctx_{idx}.json"
        write_snapshot(path, {"context_state": {"cookies": [], "origins": []}, "tabs": [{"url": f"https://{idx}.test"}]})
        os.utime(path, (1000 + idx, 1000 + idx))
        files.append(path)
    session_sync.update_manifest("ctx", files[0], session_sync.load_snapshot(files[0]), '["https://0.test"]')

    result = session_sync.enforce_retention({"max_saved_sessions": 2, "max_cache_mb": 1024})
    manifest = session_sync.load_manifest()

    assert result["deleted"] == 1
    assert not files[0].exists()
    assert "ctx" not in manifest["contexts"]
    assert len([path for path in tmp_path.glob("*.json") if path.name != session_sync.MANIFEST_FILE_NAME]) == 2


def test_delete_context_snapshots_removes_only_that_context_and_repairs_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    ctx_path = tmp_path / "ctx_1.json"
    other_path = tmp_path / "other_1.json"
    write_snapshot(ctx_path, {"context_state": {"cookies": [], "origins": []}, "tabs": []})
    write_snapshot(other_path, {"context_state": {"cookies": [], "origins": []}, "tabs": []})
    session_sync.update_manifest("ctx", ctx_path, session_sync.load_snapshot(ctx_path), "[]")
    session_sync.update_manifest("other", other_path, session_sync.load_snapshot(other_path), "[]")

    deleted = session_sync.delete_context_snapshots("ctx")
    manifest = session_sync.load_manifest()

    assert deleted == 1
    assert not ctx_path.exists()
    assert other_path.exists()
    assert "ctx" not in manifest["contexts"]
    assert "other" in manifest["contexts"]


def test_delete_context_snapshots_preserves_global_current_file(tmp_path, monkeypatch):
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path)
    global_path = tmp_path / "ctx_global.json"
    old_chat_path = tmp_path / "ctx_old.json"
    write_snapshot(global_path, {"context_state": {"cookies": [], "origins": []}, "tabs": []})
    write_snapshot(old_chat_path, {"context_state": {"cookies": [], "origins": []}, "tabs": []})
    session_sync.update_manifest("ctx", old_chat_path, session_sync.load_snapshot(old_chat_path), "[]")
    manifest = session_sync.load_manifest()
    manifest["global_latest"] = {
        "context_id": "ctx",
        "filename": global_path.name,
        "updated_at": 2000,
        "tab_count": 0,
        "signature": "[]",
    }
    session_sync.save_manifest(manifest)

    deleted = session_sync.delete_context_snapshots("ctx")
    manifest = session_sync.load_manifest()

    assert deleted == 1
    assert global_path.exists()
    assert not old_chat_path.exists()
    assert manifest["global_latest"]["filename"] == global_path.name


def test_webui_settings_component_uses_native_modal_actions():
    root = Path(__file__).resolve().parents[1]
    html = (root / "webui/config.html").read_text(encoding="utf-8")

    assert "parentContext" in html
    assert "__pluginSettingsContext" in html
    assert "wizardFooter" in html
    assert "backLabel: () => this.loading ? \"Refreshing...\" : \"Refresh\"" in html
    assert "Save Settings" not in html
    assert "Reset Changes" not in html
    assert "draftConfig" not in html
    assert "$store.browserSessionSync" not in html
    assert "config-store.js" not in html
    assert "<script" not in html
    assert '@change="saveConfig"' not in html
    assert 'x-model="settings.session_scope"' in html
    assert 'value="global">Global across chats' in html
    assert 'value="chat">Current chat only' in html
    assert "--color-bg-secondary, #e2e8f0" in html


def test_browser_session_prompt_requires_list_before_opening_tabs():
    root = Path(__file__).resolve().parents[1]
    prompt_path = root / "extensions/python/system_prompt/_50_browser_session_sync.py"
    prompt_spec = importlib.util.spec_from_file_location("browser_session_sync_prompt", prompt_path)
    prompt_module = importlib.util.module_from_spec(prompt_spec)
    assert prompt_spec.loader is not None
    prompt_spec.loader.exec_module(prompt_module)

    prompt = []
    asyncio.run(prompt_module.BrowserSessionSyncPrompt(agent=None).execute(system_prompt=prompt))
    text = "\n".join(prompt)

    assert 'action: "list"' in text
    assert "browser_id" in text
    assert "context id to the `browser` tool" in text
    assert 'action: "open" merely to discover' in text


def test_plugin_config_hooks_normalize_native_modal_settings(monkeypatch):
    calls = []

    monkeypatch.setattr(session_sync, "enforce_retention", lambda config=None: calls.append(config) or {"ok": True})

    root = Path(__file__).resolve().parents[1]
    hooks_path = root / "hooks.py"
    hooks_spec = importlib.util.spec_from_file_location("browser_session_sync_hooks", hooks_path)
    hooks_module = importlib.util.module_from_spec(hooks_spec)
    assert hooks_spec.loader is not None
    hooks_spec.loader.exec_module(hooks_module)

    loaded = hooks_module.get_plugin_config(default={"enabled": False, "allow_global_fallback": True})
    saved = hooks_module.save_plugin_config(settings={"session_scope": "chat", "max_saved_sessions": 0})

    assert loaded["session_scope"] == "global"
    assert "enabled" not in loaded
    assert "allow_global_fallback" not in loaded
    assert saved["session_scope"] == "chat"
    assert saved["max_saved_sessions"] == 1
    assert calls == [saved]


def test_sync_reset_and_remove_extensions_return_none(monkeypatch):
    calls = []

    def fake_reset(context_id):
        calls.append(("reset", context_id))

    def fake_remove(context_id):
        calls.append(("remove", context_id))

    monkeypatch.setattr(session_sync, "handle_context_reset_sync", fake_reset)
    monkeypatch.setattr(session_sync, "handle_context_remove_sync", fake_remove)

    root = Path(__file__).resolve().parents[1]
    reset_path = root / "extensions/python/_functions/agent/AgentContext/reset/start/_05_save_browser_session.py"
    remove_path = root / "extensions/python/_functions/agent/AgentContext/remove/start/_05_save_browser_session.py"

    reset_spec = importlib.util.spec_from_file_location("reset_save_browser_session", reset_path)
    remove_spec = importlib.util.spec_from_file_location("remove_save_browser_session", remove_path)
    reset_module = importlib.util.module_from_spec(reset_spec)
    remove_module = importlib.util.module_from_spec(remove_spec)
    assert reset_spec.loader is not None
    assert remove_spec.loader is not None
    reset_spec.loader.exec_module(reset_module)
    remove_spec.loader.exec_module(remove_module)

    assert reset_module.SaveBrowserSession(agent=None).execute(data={"args": (SimpleNamespace(id="ctx"),)}) is None
    assert remove_module.SaveBrowserSession(agent=None).execute(data={"args": ("ctx",)}) is None
    assert calls == [("reset", "ctx"), ("remove", "ctx")]
