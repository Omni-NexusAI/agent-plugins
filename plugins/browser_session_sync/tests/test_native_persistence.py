import asyncio
import contextvars
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from usr.plugins.browser_session_sync.helpers import session_sync as sync, native_adapter
from test_session_sync import FakeCore, FakePage, write_snapshot


@pytest.mark.parametrize("point,class_name", [
    ("startup_migration", "BrowserSessionNativeStartup"),
    ("agent_init", "BrowserSessionNativeAgent"),
])
def test_initialization_hooks_run_through_host_synchronous_dispatcher(monkeypatch, point, class_name):
    from helpers import extension
    module = importlib.import_module(
        f"usr.plugins.browser_session_sync.extensions.python.{point}._45_browser_session_native")
    patched = []
    monkeypatch.setattr(native_adapter, "patch_runtime", lambda: patched.append(True))
    monkeypatch.setattr(extension, "_get_extension_classes", lambda *args, **kwargs: [getattr(module, class_name)])
    monkeypatch.setattr(extension, "_log_extension_call", lambda *args: None)
    extension.call_extensions_sync(point, None)
    assert patched == [True]


@pytest.fixture
def core(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(sync, "auto_restore_enabled", lambda: True)
    monkeypatch.setattr(sync, "auto_save_enabled", lambda: True)
    monkeypatch.setattr(sync, "session_scope", lambda: "global")
    monkeypatch.setattr(sync, "max_auto_restore_tabs", lambda: 0)
    core = FakeCore("shared")
    core.current_context_id = "ctx"
    core.request_context_id = contextvars.ContextVar("test", default="shared")
    core._restore_state_exists = False
    core._restore_entries = []
    core._session_sync_empty_profile = False
    core._session_sync_native_tabs_absent = False
    snapshot = {"context_state": {"cookies": [{"name": "test", "value": "fixture"}], "origins": []},
        "tabs": [{"url": "https://fixture.test", "context_id": "ctx"}], "context_id": "shared"}
    path = tmp_path / "shared_fixture.json"
    write_snapshot(path, snapshot)
    monkeypatch.setattr(sync, "select_best_snapshot", lambda *args, **kwargs: (path, snapshot))
    return core


@pytest.mark.parametrize("empty,absent,exists,storage,tabs", [
    (False, False, True, False, False), (True, False, True, True, False),
    (False, True, False, False, True), (True, True, False, True, True),
    (False, False, False, False, False),
])
def test_native_profile_and_tab_authority(core, empty, absent, exists, storage, tabs):
    core._session_sync_empty_profile = empty
    core._session_sync_native_tabs_absent = absent
    core._restore_state_exists = exists
    asyncio.run(sync.prepare_native_fallback(core))
    assert bool(core.context.added_cookies) == storage
    assert bool(core._restore_entries) == tabs


def test_existing_local_storage_prevents_automatic_signin_injection(core):
    core._session_sync_empty_profile = True
    core.context.origins = [{"origin": "https://native.test"}]
    asyncio.run(sync.prepare_native_fallback(core))
    assert not core.context.added_cookies


def test_snapshot_preserves_owners_and_global_cache_survives_chat_cleanup(core):
    core.pages[1] = SimpleNamespace(page=FakePage("https://fixture.test"), context_id="other")
    snapshot = asyncio.run(sync.capture_snapshot(core))
    assert snapshot["tabs"][0]["context_id"] == "other"
    assert snapshot["context_id"] == "shared"
    path = sync.SAVE_DIR / "shared_1.json"
    write_snapshot(path, snapshot)
    sync.delete_context_snapshots("ctx")
    assert path.exists()


def test_old_snapshot_never_reassigns_other_chat():
    assert sync.snapshot_tab_owner({}, {}, Path("other_1.json"), "ctx") == ""
    assert sync.snapshot_tab_owner({}, {}, Path("ctx_1.json"), "ctx") == "ctx"


def test_shared_snapshot_updates_chat_lookup_even_when_last_tab_closes(core):
    path = sync.SAVE_DIR / 'shared_first.json'
    first = {'context_id': 'shared', 'tabs': [{'context_id': 'ctx', 'url': 'https://fixture.test'}]}
    write_snapshot(path, first)
    sync.update_manifest('shared', path, first, 'first')
    assert sync.load_manifest()['contexts']['ctx']['filename'] == path.name
    path = sync.SAVE_DIR / 'shared_empty.json'
    empty = {'context_id': 'shared', 'tabs': []}
    write_snapshot(path, empty)
    sync.update_manifest('shared', path, empty, 'empty')
    assert sync.load_manifest()['contexts']['ctx']['filename'] == path.name


def test_profile_emptiness_is_conservative(tmp_path):
    assert native_adapter.profile_is_empty(tmp_path / "absent")
    assert native_adapter.profile_is_empty(tmp_path)
    (tmp_path / "unclassified").mkdir()
    assert not native_adapter.profile_is_empty(tmp_path)


def test_shared_worker_sets_and_resets_request_context(core, monkeypatch):
    from plugins._browser.helpers import runtime
    monkeypatch.setattr(native_adapter, "patch_runtime", lambda: True)
    calls = []
    class Worker:
        async def execute_inside(self, callback):
            calls.append("worker")
            return await callback()
    session = SimpleNamespace(_runtime=SimpleNamespace(_core=core, _worker=Worker()))
    async def get_runtime(*args, **kwargs): return session
    monkeypatch.setattr(runtime, "get_runtime", get_runtime)
    async def callback(value):
        assert value.request_context_id.get() == "ctx"
        raise RuntimeError("test exception")
    with pytest.raises(RuntimeError, match="test exception"):
        asyncio.run(sync._run_with_core_started("ctx", callback))
    assert calls == ["worker"] and core.request_context_id.get() == "shared"


def test_native_startup_injects_before_navigation_once(core, monkeypatch, tmp_path):
    events = []
    class NativeCore:
        def _adopt_legacy_profile(self, context_id): events.append("adopt")
        async def _start(self):
            self._adopt_legacy_profile("ctx")
            events.append("launch")
        async def _restore_tabs_for_scope(self): events.append("navigate")
    fake_runtime = SimpleNamespace(_BrowserRuntimeCore=NativeCore, BrowserRuntimeSession=object,
        kvp=SimpleNamespace(get_persistent=lambda *args: None), BROWSER_TABS_KEY='fixture')
    monkeypatch.setattr(native_adapter.importlib, "import_module", lambda name: fake_runtime)
    async def fallback(value):
        assert value._session_sync_empty_profile
        events.append("storage")
    monkeypatch.setattr(sync, "prepare_native_fallback", fallback)
    monkeypatch.setattr(sync, "register_auto_save", lambda value: events.append("listeners"))
    assert native_adapter.patch_runtime()
    assert native_adapter.patch_runtime()
    instance = NativeCore()
    instance.profile_dir = tmp_path / 'empty'
    async def start():
        await instance._start()
        await instance._restore_tabs_for_scope()
    asyncio.run(start())
    assert events == ['adopt', 'launch', 'listeners', 'storage', 'navigate']


def test_manual_recovery_deduplicates_and_preserves_other_chat(core, monkeypatch):
    monkeypatch.setattr(sync, "schedule_save", lambda *args, **kwargs: None)
    core._persist_browser_tabs = lambda: None
    async def register(page, owner):
        item = SimpleNamespace(id=len(core.pages)+1, page=page, context_id=owner)
        core.pages[item.id] = item
        return item
    core._register_page = register
    asyncio.run(sync.restore_core_session(core, force=True))
    message = asyncio.run(sync.restore_core_session(core, force=True))
    assert len(core.pages) == 1
    assert 'Restored 0 tabs' in message and 'Shared sign-in' in message


def test_manual_tool_response_matches_host(monkeypatch, tmp_path):
    from usr.plugins.browser_session_sync.tools import browser_session_restore as tool
    monkeypatch.setattr(tool, 'SAVE_DIR', tmp_path)
    instance = tool.BrowserSessionRestore(agent=SimpleNamespace(context=SimpleNamespace(id='ctx')),
        name='browser_session_restore', method=None, args={}, message='', loop_data=None)
    response = asyncio.run(instance.execute(list=True))
    assert response.message == 'No saved browser sessions found.'
    assert response.break_loop is False
