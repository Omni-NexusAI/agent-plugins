"""Guarded adapter between finite System 1 choices and Agent Zero calls."""

from __future__ import annotations

import json
import os

from helpers import plugins
from usr.plugins.system_1.helpers.system_1_core import DecisionClient, DecisionError
from usr.plugins.system_1.helpers.system_1_core.decision import selected_action


PLUGIN = "system_1"
SPECIALIST_ROUTE_KEY = "system_1_specialist_route"


def config_for(agent, section: str) -> tuple[dict, dict] | None:
    config = plugins.get_plugin_config(PLUGIN, agent)
    if not isinstance(config, dict):
        return None
    section_config = config.get(section)
    if not isinstance(section_config, dict) or not section_config.get("enabled"):
        return None
    return section_config, config.get("policy", {}) if isinstance(config.get("policy"), dict) else {}


def client_for(section_config: dict, policy: dict) -> DecisionClient:
    token_env = section_config.get("token_env", "")
    token = os.environ.get(token_env, "") if isinstance(token_env, str) and token_env else ""
    if section_config.get("backend") == "jev" and not token:
        raise DecisionError("Jev key is unavailable; configure the named environment variable")
    return DecisionClient(backend=section_config.get("backend", ""),
                          model=section_config.get("model", ""),
                          endpoint=section_config.get("endpoint", ""), token=token,
                          timeout=float(policy.get("timeout_seconds", 2)))


def allowed_actions(policy: dict) -> dict:
    actions = policy.get("actions", {})
    if not isinstance(actions, dict):
        return {}
    return {key: value for key, value in actions.items()
            if isinstance(key, str) and key and isinstance(value, dict)
            and isinstance(value.get("tool_name"), str)
            and isinstance(value.get("tool_args", {}), dict)}


async def main_decision(agent) -> str | None:
    # A fixed action is eligible only once per user turn. Later iterations
    # belong to the host's tool-result/reasoning loop.
    if getattr(getattr(agent, "loop_data", None), "iteration", 0) != 1:
        return None
    settings = config_for(agent, "main")
    if not settings:
        return None
    section, policy = settings
    agent.set_data(SPECIALIST_ROUTE_KEY, "")
    text = agent.last_user_message.output_text() if agent.last_user_message else ""
    if not text.strip():
        return None
    actions = allowed_actions(policy)
    choices = {"main": "Use Main for complex, uncertain, or open-ended reasoning and actions."}
    choices.update({key: value.get("description", key) for key, value in actions.items() if key != "main"})
    try:
        from usr.plugins.auxiliary_model_roles.helpers.runtime import available_roles
        roles = available_roles(agent)
    except ImportError:
        roles = {}
    if policy.get("action_precedence") == "tool_first" and "tool" in roles:
        agent.set_data(SPECIALIST_ROUTE_KEY, "tool")
        return None
    for role in roles:
        choices[f"specialist_{role}"] = f"Delegate a bounded {role} task to the configured specialist."
    if len(choices) < 2:
        return None
    try:
        client = client_for(section, policy)
        result = await client.choose(text[:int(policy.get("max_state_chars", 4000))], choices)
        if result.choice.startswith("specialist_") and result.confidence >= float(policy.get("min_choice_probability", 0.85)):
            agent.set_data(SPECIALIST_ROUTE_KEY, result.choice.removeprefix("specialist_"))
            return None
        action = selected_action(result, actions, threshold=float(policy.get("min_choice_probability", 0.85)))
        if action:
            return json.dumps(action, separators=(",", ":"))
    except (DecisionError, ValueError, TypeError, OSError):
        pass
    return None


async def utility_decision(agent, call_data: dict) -> None:
    settings = config_for(agent, "utility")
    if not settings:
        return
    section, policy = settings
    message = call_data.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return
    try:
        result = await client_for(section, policy).choose(
            message[:int(policy.get("max_state_chars", 4000))],
            {"ordinary": "Run the usual utility model without change.",
             "memory": "This is memory organization or prompt preparation; favor precise, conservative output."})
        if result.choice == "memory" and result.confidence >= float(policy.get("min_choice_probability", 0.85)):
            call_data["system"] += "\nSystem 1 classification: memory or prompt preparation. Preserve facts and provenance; avoid inventing memory."
    except (DecisionError, ValueError, TypeError, OSError):
        return


async def memory_decision(agent, state: str, purpose: str) -> str:
    """Advice for memory hooks. This never changes the embedding model or index."""
    settings = config_for(agent, "embedding")
    if not settings or not state.strip():
        return "normal"
    section, policy = settings
    try:
        result = await client_for(section, policy).choose(
            state[:int(policy.get("max_state_chars", 4000))],
            {"normal": f"Use normal {purpose} with the configured embedding model.",
             "precise": f"Use precise {purpose}, retaining only task-relevant information."})
        return result.choice if result.confidence >= float(policy.get("min_choice_probability", 0.85)) else "normal"
    except (DecisionError, ValueError, TypeError, OSError):
        return "normal"
