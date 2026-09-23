"""Build optional specialists from current config and return work to Main."""

from __future__ import annotations

import asyncio

from helpers import plugins


PLUGIN = "auxiliary_model_roles"
ROLES = {"tool", "coding"}


def available_roles(agent) -> dict[str, dict]:
    config = plugins.get_plugin_config(PLUGIN, agent)
    if not isinstance(config, dict):
        return {}
    return {role: section for role in ROLES
            if isinstance((section := config.get(role)), dict)
            and section.get("enabled")
            and isinstance(section.get("provider"), str) and section["provider"].strip()
            and isinstance(section.get("name"), str) and section["name"].strip()}


async def delegate(agent, role: str, goal: str) -> str:
    if role not in ROLES:
        raise ValueError("Unknown specialist role")
    section = available_roles(agent).get(role)
    if not section:
        raise ValueError(f"{role.title()} specialist is disabled or not configured")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("A delegation goal is required")
    config = plugins.get_plugin_config(PLUGIN, agent) or {}
    policy = config.get("policy", {}) if isinstance(config.get("policy"), dict) else {}
    max_chars = max(100, min(16000, int(policy.get("max_goal_chars", 8000))))
    timeout = max(1.0, min(300.0, float(policy.get("timeout_seconds", 90))))
    if len(goal) > max_chars:
        raise ValueError("Delegation goal exceeds the configured limit")

    import models
    from plugins._model_config.helpers.model_config import build_model_config

    model_config = build_model_config(section, models.ModelType.CHAT)
    model = models.get_chat_model(model_config.provider, model_config.name,
                                  model_config=model_config, **model_config.build_kwargs())
    if role == "tool":
        instruction = ("You are a Tool specialist working for Agent Zero Main. Return concise findings "
                       "and any proposed tool name and arguments as a JSON object. Do not claim a tool was "
                       "executed. Main will decide and perform authorized actions through the host.")
    else:
        instruction = ("You are a Coding specialist working for Agent Zero Main. Solve the delegated "
                       "coding goal and return code, reasoning, test results or a precise escalation. "
                       "Do not claim edits or tests that you did not perform.")
    response, _reasoning = await asyncio.wait_for(
        model.unified_call(system_message=instruction, user_message=goal), timeout=timeout)
    if role not in available_roles(agent):
        raise RuntimeError(f"{role.title()} specialist was disabled during the request")
    if not isinstance(response, str) or not response.strip():
        raise RuntimeError(f"{role.title()} specialist returned no result")
    return response.strip()[:32_000]
