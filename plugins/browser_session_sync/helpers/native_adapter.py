"""Guarded integration with the shared persistent Browser runtime (A0 2.11)."""
from __future__ import annotations

import functools
import importlib
import inspect
import logging

logger = logging.getLogger("browser_session_sync")


def profile_is_empty(path) -> bool:
    """Only absent or literally empty profiles are proven empty; never inspect data."""
    try:
        if path.is_symlink():
            return False
        path.stat()
        return path.is_dir() and next(path.iterdir(), None) is None
    except FileNotFoundError:
        return True
    except OSError:
        return False


def patch_runtime() -> bool:
    try:
        runtime = importlib.import_module("plugins._browser.helpers.runtime")
        core_type = runtime._BrowserRuntimeCore
        if getattr(core_type, "_session_sync_native_patched", False):
            return True
        # Fail closed on unknown hosts; legacy extension hooks remain available.
        for name in ("_start", "_adopt_legacy_profile", "_restore_tabs_for_scope"):
            if not callable(getattr(core_type, name, None)):
                return False
        if list(inspect.signature(core_type._adopt_legacy_profile).parameters) != ["self", "context_id"]:
            return False
        if not hasattr(runtime, "BrowserRuntimeSession"):
            return False
    except (ImportError, AttributeError, ValueError):
        return False

    original_adopt = core_type._adopt_legacy_profile
    original_start = core_type._start

    @functools.wraps(original_adopt)
    def adopt(core, context_id):
        result = original_adopt(core, context_id)
        # This point is after native legacy-profile adoption, before Chromium
        # creates profile files or navigates restored tabs.
        core._session_sync_empty_profile = profile_is_empty(core.profile_dir)
        return result

    @functools.wraps(original_start)
    async def start(core, *args, **kwargs):
        from usr.plugins.browser_session_sync.helpers import session_sync as sync

        core._session_sync_empty_profile = False
        core._session_sync_native_tabs_absent = False
        pending = getattr(core, sync.SAVE_HANDLE_ATTR, None)
        if pending:
            pending.cancel()
        setattr(core, sync.SAVE_SIGNATURE_ATTR, None)
        setattr(core, sync.SAVE_LAST_AT_ATTR, 0)
        try:
            # Native's loader treats corrupt/unreadable state like absence.
            # Recovery must distinguish those cases from true absence.
            core._session_sync_native_tabs_absent = runtime.kvp.get_persistent(runtime.BROWSER_TABS_KEY, None) is None
        except Exception:
            pass
        await original_start(core, *args, **kwargs)
        # A replacement context needs fresh listeners even when core is reused.
        setattr(core, sync.LISTENERS_FLAG, False)
        setattr(core, sync.RESTORED_FLAG, False)
        try:
            sync.register_auto_save(core)
            await sync.prepare_native_fallback(core)
        except Exception:
            logger.warning("Browser cache fallback unavailable; native persistence remains authoritative.", exc_info=True)

    core_type._adopt_legacy_profile = adopt
    core_type._start = start
    core_type._session_sync_native_patched = True
    return True
