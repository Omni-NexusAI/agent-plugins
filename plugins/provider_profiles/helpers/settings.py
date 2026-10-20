"""Plugin settings merged over defaults.

Agent Zero replaces default_config.yaml wholesale once a config.json exists, so
defaults are re-applied here in code and every value is validated.
"""
from __future__ import annotations

from typing import Any

PLUGIN_NAME = "provider_profiles"

BUILTIN_LOCAL_DEFAULTS = {
    "lm_studio": "http://host.docker.internal:1234/v1",
    "ollama": "http://host.docker.internal:11434",
}

DEFAULTS: dict[str, Any] = {
    "favorites_ui": "auto",
    "favorites_shown": 5,
    "normal_results_mode": "narrow",
    "local_provider_defaults": dict(BUILTIN_LOCAL_DEFAULTS),
    "clear_stale_model_on_new_provider": True,
}

FAVORITES_UI = ("auto", "on", "off")
NORMAL_RESULTS_MODES = ("narrow", "core")
SHOWN_RANGE = (1, 20)


def merge_settings(raw: Any) -> dict[str, Any]:
    """Return a complete, validated settings dict; unknown keys are ignored."""
    merged = {key: (dict(value) if isinstance(value, dict) else value) for key, value in DEFAULTS.items()}
    if not isinstance(raw, dict):
        return merged

    if raw.get("favorites_ui") in FAVORITES_UI:
        merged["favorites_ui"] = raw["favorites_ui"]
    if raw.get("normal_results_mode") in NORMAL_RESULTS_MODES:
        merged["normal_results_mode"] = raw["normal_results_mode"]

    shown = raw.get("favorites_shown")
    if isinstance(shown, bool):
        shown = None
    if isinstance(shown, str) and shown.strip().isdigit():
        shown = int(shown.strip())
    if isinstance(shown, float) and shown.is_integer():
        shown = int(shown)
    if isinstance(shown, int) and SHOWN_RANGE[0] <= shown <= SHOWN_RANGE[1]:
        merged["favorites_shown"] = shown

    defaults = raw.get("local_provider_defaults")
    if isinstance(defaults, dict):
        for key in BUILTIN_LOCAL_DEFAULTS:
            value = defaults.get(key)
            if isinstance(value, str) and value.strip():
                merged["local_provider_defaults"][key] = value.strip()

    if isinstance(raw.get("clear_stale_model_on_new_provider"), bool):
        merged["clear_stale_model_on_new_provider"] = raw["clear_stale_model_on_new_provider"]
    return merged
