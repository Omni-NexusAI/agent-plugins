from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers.extension import Extension


def _source_helper():
    plugin_root = Path(__file__).resolve().parents[3]
    helper_path = plugin_root / "helpers" / "source.py"
    spec = importlib.util.spec_from_file_location("agentspine_multi_source_updater_startup", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Multi Source Updater helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MultiSourceUpdaterStartup(Extension):
    def execute(self, **kwargs):
        _source_helper().patch_self_update()
