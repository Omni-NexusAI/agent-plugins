from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers.api import ApiHandler, Request


def _source_helper():
    helper_path = Path(__file__).resolve().parent.parent / "helpers" / "source.py"
    spec = importlib.util.spec_from_file_location("agentspine_multi_source_updater_api", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Multi Source Updater helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Source(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict:
        helper = _source_helper()
        if "update_source" in input:
            selected = helper.set_active_source_key(str(input.get("update_source") or ""))
        else:
            selected = helper.get_active_source_key()
        helper.patch_self_update()
        return {
            "success": True,
            "active_update_source": selected,
            "active_update_remote_url": helper.remote_url(selected),
            "update_sources": helper.source_options(),
            "source_execution": helper.get_execution_state(selected),
        }
