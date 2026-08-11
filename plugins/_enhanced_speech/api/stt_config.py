"""Plugin-owned persistence bridge for Whisper STT settings.

The host Whisper modal has changed across compatible Agent Zero releases. This
route owns only Enhanced Speech's mirrored provider settings so a selected
processing device survives a native modal save without touching host-core
configuration.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

from helpers.api import ApiHandler, Request


WHISPER_PLUGIN = "_whisper_stt"
WHISPER_SETTING_KEYS = (
    "model_size",
    "device",
    "language",
    "message_mode",
    "silence_threshold",
    "silence_duration",
    "waiting_timeout",
)


def _helper_from(filename: str, module_name: str):
    helper_path = Path(__file__).resolve().parent.parent / "helpers" / filename
    spec = importlib.util.spec_from_file_location(module_name, helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Enhanced Speech helper is unavailable: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config_helper():
    return _helper_from("config.py", "agentspine_enhanced_speech_stt_config")


def _gpu_helper():
    return _helper_from("gpu.py", "agentspine_enhanced_speech_stt_config_gpu")


def _runtime_root() -> Path:
    source = Path(__file__).resolve()
    # This package may be a Spine built-in or an A0 custom plugin. The latter
    # adds an extra ``usr`` path segment, so discover the host root rather than
    # using the built-in package's fixed parent depth.
    for candidate in source.parents:
        if (candidate / "plugins").is_dir() and (candidate / "usr").is_dir():
            return candidate
    raise RuntimeError("Unable to locate the Agent Zero runtime root")


def _plugin_config_path(plugin_name: str) -> Path:
    return _runtime_root() / "usr" / "plugins" / plugin_name / "config.json"


def _read_config(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_config_atomically(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _whisper_enabled() -> bool:
    root = _runtime_root()
    enabled = True
    for plugin_root in (
        root / "plugins" / WHISPER_PLUGIN,
        root / "usr" / "plugins" / WHISPER_PLUGIN,
    ):
        if enabled:
            enabled = not (
                (plugin_root / ".toggle-0").is_file()
                or (plugin_root / ".disabled").is_file()
            )
        elif (
            (plugin_root / ".toggle-1").is_file()
            or (plugin_root / ".enabled").is_file()
        ):
            enabled = True
    return enabled


def _runtime_config(helper) -> dict:
    enhanced = _read_config(_plugin_config_path("_enhanced_speech"))
    stt = enhanced.get("stt") if isinstance(enhanced.get("stt"), dict) else {}
    enhanced_whisper = (
        stt.get("whisper") if isinstance(stt.get("whisper"), dict) else {}
    )
    provider = _read_config(_plugin_config_path(WHISPER_PLUGIN))
    merged = dict(enhanced_whisper)
    merged.update(provider)
    return helper.normalize_whisper_config(merged)


def _with_device_metadata(config: dict) -> dict:
    result = dict(config)
    effective, label = _gpu_helper().resolve_local_device(
        str(result.get("device") or "auto")
    )
    result["effective_device"] = effective
    result["effective_device_label"] = label
    result["cuda_devices"] = _gpu_helper().get_cuda_devices()
    return result


def _save_runtime_config(helper, requested: dict) -> dict:
    normalized = helper.normalize_whisper_config({**_runtime_config(helper), **requested})

    provider_path = _plugin_config_path(WHISPER_PLUGIN)
    provider = _read_config(provider_path)
    provider.update(helper.provider_whisper_config(normalized))
    _write_config_atomically(provider_path, provider)

    enhanced_path = _plugin_config_path("_enhanced_speech")
    enhanced = _read_config(enhanced_path)
    stt = enhanced.setdefault("stt", {})
    if not isinstance(stt, dict):
        stt = enhanced["stt"] = {}
    stt["provider"] = "whisper"
    stt["whisper"] = dict(normalized)
    _write_config_atomically(enhanced_path, enhanced)
    return normalized


def _notify_saved_config(config: dict) -> None:
    try:
        from helpers.notification import (
            NotificationManager,
            NotificationPriority,
            NotificationType,
        )

        NotificationManager.send_notification(
            NotificationType.SUCCESS,
            NotificationPriority.NORMAL,
            "Whisper settings saved: "
            f"{config.get('model_size', 'base')} on "
            f"{config.get('effective_device_label', config.get('device', 'Auto'))}.",
            title="Enhanced Speech",
            display_time=5,
            group="enhanced-speech-stt-config",
        )
    except Exception:
        return


class SttConfig(ApiHandler):
    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict:
        helper = _config_helper()
        if not isinstance(input, dict) or not input:
            return {
                "success": True,
                "enabled": _whisper_enabled(),
                "config": _with_device_metadata(_runtime_config(helper)),
            }

        requested = {key: input[key] for key in WHISPER_SETTING_KEYS if key in input}
        config = _with_device_metadata(_save_runtime_config(helper, requested))
        _notify_saved_config(config)
        return {
            "success": True,
            "enabled": _whisper_enabled(),
            "config": config,
        }
