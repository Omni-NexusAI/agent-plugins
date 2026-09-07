"""Never let unit tests touch an installed host's plugin settings or cache."""
import pytest
from helpers import plugins
from usr.plugins.browser_session_sync.helpers import session_sync


@pytest.fixture(autouse=True)
def isolate_host_config(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("Host config writes/reads are disabled in unit tests")
    monkeypatch.setattr(plugins, "get_plugin_config", unavailable)
    monkeypatch.setattr(plugins, "save_plugin_config", unavailable)
    monkeypatch.setattr(plugins, "determined_toggle_from_paths", lambda *args, **kwargs: True)
    monkeypatch.setattr(session_sync, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(session_sync, "PLUGIN_DIR", tmp_path)
    monkeypatch.setattr(session_sync, "SAVE_DIR", tmp_path / "sessions")
