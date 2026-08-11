from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers.extension import Extension


def _load_config_helper():
    plugin_root = Path(__file__).resolve().parents[8]
    helper_path = plugin_root / "helpers" / "config.py"
    spec = importlib.util.spec_from_file_location("agentspine_enhanced_speech_config", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load enhanced speech config helper from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnhancedSpeechGetConfig(Extension):
    def execute(self, data=None, **kwargs):
        if not isinstance(data, dict):
            return
        args = data.get("args") or ()
        if len(args) < 2 or not isinstance(args[1], dict):
            return
        payload = args[1]
        plugin_name = payload.get("plugin_name", "")
        # This hook runs *inside* Plugins.get_plugin_config(). Re-entering that
        # helper to assemble an aggregate Enhanced Speech config recursively
        # invokes this very hook, which can stall the Kokoro status request and
        # hide its Voice Settings card. The host's just-returned provider data
        # is sufficient for the only provider we normalize here.
        if plugin_name != "_kokoro_tts":
            return
        result = data.get("result")
        if not isinstance(result, dict) or not result.get("ok"):
            return
        settings = result.get("data") if isinstance(result.get("data"), dict) else {}
        result["data"] = _load_config_helper().provider_kokoro_config(settings)
