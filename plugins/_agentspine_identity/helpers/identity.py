from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any


PLUGIN_DIR = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "product_name": "Agentspine",
    "short_name": "AS",
    "banner_prefix": "M",
    "main_release_prefix": "M",
    "development_prefix": "D",
    "compatibility_label": "A0-compatible",
    "default_release_tag": "v0.9.9-standard",
}

PROTECTED_PHRASES = {
    "Agent Zero Venice": "__AS_IDENTITY_AGENT_ZERO_VENICE__",
}


def is_identity_enabled() -> bool:
    """Identity is an explicit Spine 9.9 release feature, never an A0 shim."""
    return (
        os.getenv("AGENTSPINE_RELEASE", "").strip() == "9.9"
        and os.getenv("AGENTSPINE_IDENTITY_ENABLED", "").strip().lower() == "true"
    )

REPLACEMENTS = (
    ("Agent-Zero", "Agentspine"),
    ("AgentZero", "Agentspine"),
    ("Agent Zero", "Agentspine"),
    ("agent-zero", "agentspine"),
    ("agent zero", "Agentspine"),
    ("A0 MCP Server", "AS MCP Server"),
    ("A0 A2A Server", "AS A2A Server"),
    ("A0 instance", "AS instance"),
    ("A0-compatible", "A0-compatible"),
)


@lru_cache(maxsize=1)
def get_identity_config() -> dict[str, Any]:
    config = dict(DEFAULTS)
    config_path = PLUGIN_DIR / "default_config.yaml"
    if config_path.exists():
        loaded = _load_simple_yaml(config_path)
        config.update({k: v for k, v in loaded.items() if v not in (None, "")})
    return config


def _load_simple_yaml(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_map: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current_map = line[:-1].strip()
            result[current_map] = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if line.startswith(" ") and current_map and isinstance(result.get(current_map), dict):
            result[current_map][key] = value
        else:
            current_map = None
            result[key] = value
    return result


def default_release_tag() -> str:
    return str(get_identity_config().get("default_release_tag") or DEFAULTS["default_release_tag"])


def release_tag_for_variant(variant: str | None = None) -> str:
    """Resolve an identity label from the explicit Compose build variant."""
    config = get_identity_config()
    release_tags = config.get("release_tags")
    release_tags = release_tags if isinstance(release_tags, dict) else {}
    normalized = str(variant or "").strip().lower()
    if normalized in {"cuda", "gpu", "fullgpu"}:
        return str(
            release_tags.get("gpu")
            or release_tags.get("gpu_pre")
            or "v0.9.9-gpu"
        )
    return str(
        release_tags.get("standard")
        or release_tags.get("standard_pre")
        or default_release_tag()
    )


def normalize_release_tag(version_id: str | None) -> str:
    raw = (version_id or "").strip()
    if not raw:
        return default_release_tag()
    if raw == "v0.9.9-pre":
        return default_release_tag()
    return raw


def _is_development_release(tag: str) -> bool:
    normalized = tag.strip().lower()
    return normalized.endswith("-pre") or "-dev" in normalized


def format_timestamp(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def friendly_version_label(version_id: str | None) -> str:
    config = get_identity_config()
    tag = normalize_release_tag(version_id)
    prefix_key = "development_prefix" if _is_development_release(tag) else "main_release_prefix"
    prefix = str(config.get(prefix_key) or DEFAULTS[prefix_key])
    return f"{prefix} {tag}"


def format_display_version(
    version_id: str | None,
    timestamp: str | None = None,
    existing_display: str | None = None,
) -> str:
    existing = (existing_display or "").strip()
    if existing.startswith(("D ", "M ", "AS ")):
        return existing
    label = friendly_version_label(version_id)
    formatted_time = format_timestamp(timestamp)
    return f"{label} {formatted_time}".strip()


def apply_identity_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text

    result = text
    for phrase, token in PROTECTED_PHRASES.items():
        result = result.replace(phrase, token)
    for source, target in REPLACEMENTS:
        result = result.replace(source, target)
    for phrase, token in PROTECTED_PHRASES.items():
        result = result.replace(token, phrase)
    return result
