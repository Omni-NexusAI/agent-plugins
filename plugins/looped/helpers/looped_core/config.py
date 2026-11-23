"""Defaults and tolerant merging of saved settings.

A host may hand back only the keys a user changed, or a complete replacement
of the defaults. ``merge_config`` fills the gaps, keeps unknown keys, and
clamps values that would make the controller misbehave.
"""

from __future__ import annotations

import copy
from typing import Any

MODES = ("off", "manual", "auto", "always")
EXECUTION = ("auto", "sequential", "parallel")
SHOW_STEPS = ("all", "changed", "none")
REREAD_WHEN = ("non_thinking", "always", "never")
CHECKPOINTS = ("first_step", "risky_tool", "final_response", "after_error",
               "invalid_step")

DEFAULTS: dict[str, Any] = {
    "mode": "manual",
    "apply_to_subordinates": False,
    "execution": "auto",
    "show_steps": "all",
    "budget": {
        "max_extra_calls_per_step": 1,
        "allow_tiebreak": True,
        "max_extra_calls_per_turn": 8,
    },
    "sampling": {
        "temperature": 0.7,
        "seed_base": 1000,
    },
    "strategies": {
        "reread": {"enabled": True, "when": "non_thinking", "max_chars": 4000},
        "agree": {"enabled": True},
        "fuse": {"enabled": True, "min_chars": 400},
        "retry": {"enabled": True, "max_per_turn": 2},
        "deepen": {"enabled": False},
        # carry: later passes are shown the earlier ones instead of starting from scratch.
        # reasoning_params: extra call options that switch the model's reasoning on.
        "escalate": {"enabled": False, "carry": False, "reasoning_params": {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": True}}}},
        "plan_branch": {"enabled": False, "branches": 2, "max_chars": 2000},
    },
    "auto": {
        "checkpoints": list(CHECKPOINTS),
        "risky_tools": [
            "code_execution_tool", "input", "text_editor", "memory_save",
            "memory_delete", "memory_forget", "behaviour_adjustment",
            "call_subordinate", "scheduler", "browser_agent", "browser",
            "a2a_chat", "notify_user", "parallel", "*.*",
        ],
    },
}


def _merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {key: copy.deepcopy(value) for key, value in base.items()}
        for key, value in override.items():
            merged[key] = _merge(base[key], value) if key in base else copy.deepcopy(value)
        return merged
    if isinstance(base, dict):
        # A scalar where a section is expected is a corrupt setting.
        return copy.deepcopy(base)
    return copy.deepcopy(override)


def _int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(low, min(high, int(value)))


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def merge_config(saved: Any = None) -> dict[str, Any]:
    """Return defaults overlaid with ``saved`` and normalised."""
    cfg = _merge(DEFAULTS, saved if isinstance(saved, dict) else {})
    cfg["mode"] = _choice(cfg.get("mode"), MODES, DEFAULTS["mode"])
    cfg["execution"] = _choice(cfg.get("execution"), EXECUTION, "auto")
    cfg["show_steps"] = _choice(cfg.get("show_steps"), SHOW_STEPS, "all")
    cfg["apply_to_subordinates"] = cfg.get("apply_to_subordinates") is True

    budget, base = cfg["budget"], DEFAULTS["budget"]
    budget["max_extra_calls_per_step"] = _int(
        budget.get("max_extra_calls_per_step"), base["max_extra_calls_per_step"], 0, 4)
    budget["max_extra_calls_per_turn"] = _int(
        budget.get("max_extra_calls_per_turn"), base["max_extra_calls_per_turn"], 0, 64)
    budget["allow_tiebreak"] = budget.get("allow_tiebreak") is not False

    sampling = cfg["sampling"]
    temperature = sampling.get("temperature")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        sampling["temperature"] = None
    else:
        sampling["temperature"] = max(0.0, min(2.0, float(temperature)))
    sampling["seed_base"] = _int(sampling.get("seed_base"), 1000, 0, 2**31 - 16)

    strategies, base = cfg["strategies"], DEFAULTS["strategies"]
    for name in base:
        strategies[name]["enabled"] = strategies[name].get("enabled") is True
    strategies["reread"]["when"] = _choice(
        strategies["reread"].get("when"), REREAD_WHEN, "non_thinking")
    strategies["reread"]["max_chars"] = _int(
        strategies["reread"].get("max_chars"), 4000, 0, 200_000)
    strategies["fuse"]["min_chars"] = _int(
        strategies["fuse"].get("min_chars"), 400, 0, 200_000)
    strategies["retry"]["max_per_turn"] = _int(
        strategies["retry"].get("max_per_turn"), 2, 0, 16)
    strategies["escalate"]["carry"] = strategies["escalate"].get("carry") is True
    # Call options are the host's business: a saved set replaces the default whole.
    saved_escalate = saved.get("strategies") if isinstance(saved, dict) else None
    saved_escalate = saved_escalate.get("escalate") if isinstance(saved_escalate, dict) else None
    saved_params = (saved_escalate.get("reasoning_params")
                    if isinstance(saved_escalate, dict) else None)
    strategies["escalate"]["reasoning_params"] = copy.deepcopy(
        saved_params if isinstance(saved_params, dict)
        else base["escalate"]["reasoning_params"])
    strategies["plan_branch"]["branches"] = _int(
        strategies["plan_branch"].get("branches"), 2, 2, 4)
    strategies["plan_branch"]["max_chars"] = _int(
        strategies["plan_branch"].get("max_chars"), 2000, 200, 20_000)

    auto = cfg["auto"]
    checkpoints = auto.get("checkpoints")
    auto["checkpoints"] = ([item for item in checkpoints if item in CHECKPOINTS]
                           if isinstance(checkpoints, list) else list(CHECKPOINTS))
    risky = auto.get("risky_tools")
    auto["risky_tools"] = ([item for item in risky if isinstance(item, str) and item]
                           if isinstance(risky, list)
                           else list(DEFAULTS["auto"]["risky_tools"]))
    return cfg
