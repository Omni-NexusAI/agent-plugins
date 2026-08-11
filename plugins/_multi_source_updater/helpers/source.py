"""Source-aware, plugin-local adapter for A0's self-update UI.

The stock bootstrap manager starts before Python plugins.  This module therefore
never rewrites its files or claims a selected remote will be used unless the
image was explicitly started with that same manager remote.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from typing import Any

from helpers import plugins


PLUGIN_NAME = "_multi_source_updater"
UPSTREAM_REMOTE_URL = "https://github.com/agent0ai/agent-zero.git"
UPDATE_SOURCES: dict[str, dict[str, str]] = {
    "omni-nexusai": {
        "label": "Agent Spine (Omni-NexusAI)",
        "author": "Omni-NexusAI",
        "name": "agent-zero",
        "remote_url": "https://github.com/Omni-NexusAI/agent-zero.git",
    },
    "agent0ai": {
        "label": "Agent Zero upstream (agent0ai)",
        "author": "agent0ai",
        "name": "agent-zero",
        "remote_url": UPSTREAM_REMOTE_URL,
    },
}

_CACHE_TTL_SECONDS = 60.0
_branch_cache: dict[str, tuple[float, list[str]]] = {}
_tag_cache: dict[str, tuple[float, list[str]]] = {}
_patch_lock = threading.RLock()


def normalize_source(value: str | None) -> str:
    key = str(value or "").strip().lower()
    return key if key in UPDATE_SOURCES else "omni-nexusai"


def _plugin_config() -> dict[str, Any]:
    try:
        config = plugins.get_plugin_config(PLUGIN_NAME) or {}
        return dict(config) if isinstance(config, dict) else {}
    except Exception:
        return {}


def get_active_source_key() -> str:
    return normalize_source(_plugin_config().get("update_source"))


def get_active_source() -> dict[str, str]:
    return dict(UPDATE_SOURCES[get_active_source_key()])


def source_options() -> list[dict[str, str]]:
    return [
        {"value": key, "label": details["label"]}
        for key, details in UPDATE_SOURCES.items()
    ]


def remote_url(source_key: str | None = None) -> str:
    return UPDATE_SOURCES[normalize_source(source_key or get_active_source_key())]["remote_url"]


def _normalized_remote_url(value: str | None) -> str:
    return str(value or "").strip().rstrip("/").lower()


def manager_remote_url() -> str:
    return os.getenv("A0_SELF_UPDATE_REMOTE_URL", UPSTREAM_REMOTE_URL).strip() or UPSTREAM_REMOTE_URL


def get_execution_state(source_key: str | None = None) -> dict[str, Any]:
    selected = normalize_source(source_key or get_active_source_key())
    selected_remote = remote_url(selected)
    manager_remote = manager_remote_url()
    matching_remote = _normalized_remote_url(selected_remote) == _normalized_remote_url(manager_remote)
    if selected == "omni-nexusai":
        return {
            "manager_remote_url": manager_remote,
            "selected_remote_url": selected_remote,
            "can_schedule": False,
            "note": (
                "Agent Spine source selection is active for discovery, but this A0 v2.7 "
                "bootstrap manager accepts only upstream vX.Y update targets. "
                "The plugin leaves execution blocked rather than risking an update from the wrong remote."
            ),
        }
    if matching_remote:
        return {
            "manager_remote_url": manager_remote,
            "selected_remote_url": selected_remote,
            "can_schedule": True,
            "note": "The selected upstream source matches the image bootstrap manager.",
        }
    return {
        "manager_remote_url": manager_remote,
        "selected_remote_url": selected_remote,
        "can_schedule": False,
        "note": (
            "The selected source is saved, but the image bootstrap manager is configured for a different remote. "
            "Redeploy with A0_SELF_UPDATE_REMOTE_URL set to the selected remote before scheduling an update."
        ),
    }


def clear_caches() -> None:
    _branch_cache.clear()
    _tag_cache.clear()
    try:
        from helpers import self_update

        for attribute in (
            "_remote_branch_tag_cache",
            "_remote_branch_head_cache",
        ):
            cache = getattr(self_update, attribute, None)
            if hasattr(cache, "clear"):
                cache.clear()
        if hasattr(self_update, "_remote_branch_list_cache"):
            self_update._remote_branch_list_cache = None
    except Exception:
        pass


def set_active_source_key(value: str | None) -> str:
    key = normalize_source(value)
    config = _plugin_config()
    config["update_source"] = key
    plugins.save_plugin_config(PLUGIN_NAME, "", "", config)
    clear_caches()
    patch_self_update()
    return key


def _run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        capture_output=True,
        timeout=20,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return completed.stdout.strip()


def _sort_branches(branches: list[str]) -> list[str]:
    priority = {"main": 0, "development": 1, "ready": 2, "testing": 3}
    return sorted(dict.fromkeys(branches), key=lambda value: (priority.get(value, 100), value))


def get_available_branch_values() -> list[str]:
    key = get_active_source_key()
    cached = _branch_cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] <= _CACHE_TTL_SECONDS:
        return list(cached[1])

    branches: list[str] = []
    try:
        output = _run_git("ls-remote", "--heads", remote_url(key))
        prefix = "refs/heads/"
        for line in output.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].startswith(prefix):
                branches.append(parts[1][len(prefix):])
    except Exception:
        # The UI remains usable offline and reports the source truthfully in
        # status; this fallback does not claim remote tag availability.
        branches = ["main", "development", "ready", "testing"]

    result = _sort_branches(branches)
    _branch_cache[key] = (now, result)
    return list(result)


def _is_upstream_tag(tag: str) -> bool:
    return re.fullmatch(r"v\d+\.\d+", tag.strip()) is not None


def _is_agentspine_tag(tag: str) -> bool:
    return re.fullmatch(r"v\d+\.\d+\.\d+-(?:standard|cuda)(?:-pre)?", tag.strip()) is not None


def _tag_sort_key(tag: str) -> tuple[int, int, int, int, str]:
    match = re.match(r"v(\d+)\.(\d+)(?:\.(\d+))?", tag)
    major = int(match.group(1)) if match else -1
    minor = int(match.group(2)) if match else -1
    patch = int(match.group(3)) if match and match.group(3) else -1
    return major, minor, patch, 0 if tag.endswith("-pre") else 1, tag


def get_available_tags(branch: str | None = None, *, query: str = "") -> tuple[list[str], str]:
    del branch  # Listing source tags is network-light and avoids host checkout assumptions.
    key = get_active_source_key()
    cached = _tag_cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] <= _CACHE_TTL_SECONDS:
        tags = list(cached[1])
    else:
        try:
            output = _run_git("ls-remote", "--tags", "--refs", remote_url(key))
            prefix = "refs/tags/"
            tags = []
            for line in output.splitlines():
                parts = line.split()
                if len(parts) != 2 or not parts[1].startswith(prefix):
                    continue
                tag = parts[1][len(prefix):]
                if key == "agent0ai" and _is_upstream_tag(tag):
                    tags.append(tag)
                elif key == "omni-nexusai" and _is_agentspine_tag(tag):
                    tags.append(tag)
            tags = sorted(dict.fromkeys(tags), key=_tag_sort_key, reverse=True)
            _tag_cache[key] = (now, tags)
        except Exception as exc:
            return [], str(exc)

    normalized_query = query.strip().lower()
    if normalized_query:
        tags = [tag for tag in tags if normalized_query in tag.lower()]
    return tags, ""


def get_selector_tag_options(
    branch: str | None = None,
    *,
    repo_dir: str | None = None,
    current_version: str | None = None,
) -> tuple[list[dict[str, str]], list[int], str]:
    del repo_dir, current_version
    tags, error = get_available_tags(branch)
    if error:
        return [], [], error
    options = [{"value": tag, "label": tag} for tag in tags]
    if get_active_source_key() == "agent0ai" and options:
        options.insert(0, {"value": "latest", "label": "latest"})
    return options, [], ""


def _apply_source_to_module(module: Any) -> None:
    source = get_active_source()
    module.OFFICIAL_REPO_AUTHOR = source["author"]
    module.OFFICIAL_REPO_NAME = source["name"]
    module._get_official_remote_url = lambda: remote_url()


def _annotate_update_info(info: dict[str, Any]) -> dict[str, Any]:
    selected = get_active_source_key()
    branches = get_available_branch_values()
    default_branch = "main" if "main" in branches else (branches[0] if branches else "main")
    options, higher_versions, tag_error = get_selector_tag_options(default_branch)
    result = dict(info)
    result.update(
        {
            "update_sources": source_options(),
            "active_update_source": selected,
            "active_update_remote_url": remote_url(selected),
            "source_execution": get_execution_state(selected),
            "branches": [{"value": branch, "label": branch} for branch in branches],
            "available_tag_options": options,
            "available_tags": [option["value"] for option in options],
            "available_higher_major_versions": higher_versions,
            "available_tags_error": tag_error,
        }
    )
    defaults = dict(result.get("defaults") or {})
    defaults["branch"] = default_branch
    if selected == "omni-nexusai":
        defaults["tag"] = options[0]["value"] if options else ""
    result["defaults"] = defaults
    return result


def patch_self_update() -> bool:
    """Patch only runtime callables; no `/exe` or host source is modified."""
    try:
        from helpers import self_update
    except Exception:
        return False

    with _patch_lock:
        if getattr(self_update, "_agentspine_multi_source_updater_patched", False):
            _apply_source_to_module(self_update)
            return True

        original_get_update_info = self_update.get_update_info
        original_schedule_update = self_update.schedule_update
        source_branches = globals()["get_available_branch_values"]
        source_tags = globals()["get_available_tags"]
        source_tag_options = globals()["get_selector_tag_options"]

        def get_available_branch_values(*_args: Any, **_kwargs: Any) -> list[str]:
            _apply_source_to_module(self_update)
            return source_branches()

        def get_available_branches(*_args: Any, **_kwargs: Any) -> list[dict[str, str]]:
            return [{"value": branch, "label": branch} for branch in source_branches()]

        def get_available_tags(branch: str | None = None, *_args: Any, **kwargs: Any):
            _apply_source_to_module(self_update)
            return source_tags(branch, query=str(kwargs.get("query", "") or ""))

        def get_selector_tag_options(branch: str | None = None, *_args: Any, **kwargs: Any):
            _apply_source_to_module(self_update)
            return source_tag_options(
                branch,
                repo_dir=kwargs.get("repo_dir"),
                current_version=kwargs.get("current_version"),
            )

        def get_update_info(*args: Any, **kwargs: Any) -> dict[str, Any]:
            _apply_source_to_module(self_update)
            info = original_get_update_info(*args, **kwargs)
            return _annotate_update_info(info if isinstance(info, dict) else {})

        def schedule_update(*args: Any, **kwargs: Any):
            _apply_source_to_module(self_update)
            execution = get_execution_state()
            if not execution["can_schedule"]:
                raise ValueError(str(execution["note"]))
            pending = original_schedule_update(*args, **kwargs)
            if isinstance(pending, dict):
                pending = dict(pending)
                pending["update_source"] = get_active_source_key()
                pending["remote_url"] = remote_url()
                self_update._write_yaml(self_update.get_update_file_path(), pending)
            return pending

        self_update.get_available_branch_values = get_available_branch_values
        self_update.get_available_branches = get_available_branches
        self_update.get_available_tags = get_available_tags
        self_update.get_selector_tag_options = get_selector_tag_options
        self_update.get_update_info = get_update_info
        self_update.schedule_update = schedule_update
        self_update._agentspine_multi_source_updater_patched = True
        _apply_source_to_module(self_update)
    return True
