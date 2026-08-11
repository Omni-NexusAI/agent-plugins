from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers.extension import Extension


def _source_helper():
    plugin_root = Path(__file__).resolve().parents[3]
    helper_path = plugin_root / "helpers" / "source.py"
    spec = importlib.util.spec_from_file_location("agentspine_multi_source_updater_agent", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Multi Source Updater helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MultiSourceUpdaterInit(Extension):
    def execute(self, **kwargs):
        helper = _source_helper()
        helper.patch_self_update()
        if getattr(self, "agent", None):
            self.agent.set_data("agentspine_update_source", helper.get_active_source_key())
