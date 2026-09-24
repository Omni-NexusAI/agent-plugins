"""Guarded adapter between finite System 1 choices and Agent Zero calls."""

from __future__ import annotations

from copy import deepcopy
import json
import os

from helpers import plugins
from usr.plugins.system_1.helpers.system_1_core import DecisionClient, DecisionError
from usr.plugins.system_1.helpers.system_1_core.decision import selected_action
from usr.plugins.system_1.helpers.timeline import finish_main_step


PLUGIN = "system_1"
_TURN_STATE = "_system_1_action_turn"
_MAX_ACTIONS = 8
_MAX_RESULT_CHARS = 4000


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _turn_state(agent, *, create: bool = False) -> dict | None:
    """Keep action state with this monologue, never with a later user turn."""
    loop_data = getattr(agent, "loop_data", None)
    if loop_data is None:
        return None
    state = getattr(agent, _TURN_STATE, None)
    user_message = getattr(agent, "last_user_message", None)
    if (isinstance(state, dict) and state.get("loop_data") is loop_data and
            state.get("user_message") is user_message):
        return state
    if not create:
        return None
    state = {"loop_data": loop_data, "user_message": user_message,
             "attempted_iteration": -1,
             "actions_submitted": 0, "used_action_ids": set(),
             "pending": None, "observation": None, "complete": False}
    setattr(agent, _TURN_STATE, state)
    return state


def should_decide(agent) -> bool:
    """Whether this iteration has a first request or a real host result to assess."""
    iteration = getattr(getattr(agent, "loop_data", None), "iteration", -1)
    if not isinstance(iteration, int) or iteration < 0:
        return False
    raw_state = getattr(agent, _TURN_STATE, None)
    if (isinstance(raw_state, dict) and
            raw_state.get("loop_data") is agent.loop_data and
            raw_state.get("user_message") is not getattr(agent, "last_user_message", None)):
        return False  # An intervention changed the request inside this monologue.
    state = _turn_state(agent)
    if iteration == 0:
        return not state or (not state["complete"] and state["attempted_iteration"] != 0)
    return bool(state and not state["complete"] and
                state["attempted_iteration"] != iteration and
                state["pending"] is None and state["observation"] is not None)


def record_host_result(agent, tool_name: str, tool_result: str) -> bool:
    """Accept only the host-recorded result of our pending action.

    The host calls this after executing the native or MCP tool. The plugin
    never executes a tool itself and never infers success from dispatch alone.
    """
    state = _turn_state(agent)
    pending = state.get("pending") if state else None
    if not pending or state["observation"] is not None:
        return False
    if tool_name != pending["tool_name"].split(":", 1)[0]:
        return False
    result = tool_result if isinstance(tool_result, str) else ""
    limit = pending["result_limit"]
    state["observation"] = {
        "action_id": pending["action_id"], "tool_name": pending["tool_name"],
        "action_definition": pending["action_definition"],
        "result": result[:limit] if pending["share_result"] else "",
        "return_result": result[:limit] if pending["return_result"] else "",
        "truncated": len(result) > limit,
    }
    state["pending"] = None
    return True


def delegation_action(role: str, goal: str) -> str:
    return json.dumps({"tool_name": "auxiliary_delegate", "tool_args": {
        "role": role, "goal": goal[:8000]}}, separators=(",", ":"))


def config_for(agent, section: str) -> tuple[dict, dict] | None:
    config = plugins.get_plugin_config(PLUGIN, agent)
    if not isinstance(config, dict):
        return None
    section_config = config.get(section)
    if not isinstance(section_config, dict) or not section_config.get("enabled"):
        return None
    return section_config, config.get("policy", {}) if isinstance(config.get("policy"), dict) else {}


def client_for(section_config: dict, policy: dict) -> DecisionClient:
    backend = section_config.get("backend", "")
    token_env = section_config.get("token_env", "")
    if backend == "openrouter":
        token_env = "API_KEY_OPENROUTER"
    token = os.environ.get(token_env, "") if isinstance(token_env, str) and token_env else ""
    if backend in {"jev", "openrouter"} and not token:
        raise DecisionError(f"{backend} key is unavailable")
    if backend == "chat":
        return ChatDecisionClient(section_config, policy)
    return DecisionClient(backend=backend,
                          model=section_config.get("model", ""),
                          endpoint=section_config.get("endpoint", ""), token=token,
                          timeout=float(policy.get("timeout_seconds", 2)))


class ChatDecisionClient:
    """Use Agent Zero's configured provider for bounded routing decisions.

    Chat-model confidence is self-reported, so callers must never dispatch
    fixed host actions based on this backend's answer.
    """

    def __init__(self, section_config: dict, policy: dict):
        self.section_config = section_config
        self.timeout = float(policy.get("timeout_seconds", 2))

    async def choose(self, state: str, choices: dict):
        import asyncio
        import models
        from plugins._model_config.helpers.model_config import build_model_config
        from usr.plugins.system_1.helpers.system_1_core.decision import Decision

        provider = self.section_config.get("provider", "")
        model_name = self.section_config.get("model", "")
        if not provider or not model_name or not 2 <= len(choices) <= 255:
            raise DecisionError("A provider, model, and finite choices are required")
        slot = {"provider": provider, "name": model_name,
                "api_base": self.section_config.get("endpoint", "")}
        cfg = build_model_config(slot, models.ModelType.CHAT)
        model = models.get_chat_model(cfg.provider, cfg.name,
                                      model_config=cfg, **cfg.build_kwargs())
        instruction = ("Choose exactly one of the given options. Return only a JSON object "
                       'with {"choice":"option_id","confidence":0.0}. Confidence is your '
                       "estimated probability from 0 to 1. Never invent an option.")
        answer, _ = await asyncio.wait_for(model.unified_call(
            system_message=instruction,
            user_message=json.dumps({"state": state, "choices": choices})),
            timeout=self.timeout)
        try:
            parsed = json.loads(answer)
            choice = parsed["choice"]
            confidence = float(parsed["confidence"])
            if choice not in choices or not 0 <= confidence <= 1:
                raise ValueError("Invalid choice")
            return Decision(choice, confidence, "chat")
        except (TypeError, KeyError, ValueError) as error:
            raise DecisionError("Chat provider returned no valid finite choice") from error


def allowed_actions(policy: dict) -> dict:
    actions = policy.get("actions", {})
    if not isinstance(actions, dict):
        return {}
    return {key: value for key, value in actions.items()
            if isinstance(key, str) and key not in {"", "main", "finish"}
            and not key.startswith("specialist_") and isinstance(value, dict)
            and isinstance(value.get("tool_name"), str)
            and isinstance(value.get("tool_args"), dict) and value["tool_args"]
            and isinstance(value.get("description", key), str)}


async def main_decision(agent) -> str | None:
    # Called from the host's model-call interception point on each iteration.
    # Only a first request or an observed result from our own tool can start a
    # decision. A second interception on the same iteration is ignored.
    if not should_decide(agent):
        return None
    state = _turn_state(agent, create=True)
    iteration = agent.loop_data.iteration
    state["attempted_iteration"] = iteration
    settings = config_for(agent, "main")
    if not settings:
        state["complete"] = True
        finish_main_step(agent, "Handed off to Main", detail="Mode disabled")
        return None
    section, policy = settings
    text = agent.last_user_message.output_text() if agent.last_user_message else ""
    if not text.strip():
        state["complete"] = True
        finish_main_step(agent, "Handed off to Main", detail="No request text")
        return None
    limit = _bounded_int(policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS)
    observation = state["observation"]
    if observation is not None:
        state["observation"] = None
        current_prior = allowed_actions(policy).get(observation["action_id"])
        if current_prior != observation["action_definition"]:
            observation["result"] = ""
            observation["return_result"] = ""
    actions = {key: value for key, value in allowed_actions(policy).items()
               if key not in state["used_action_ids"]}
    if state["actions_submitted"] >= limit:
        actions = {}
    choices = {"main": "Use Main for complex, uncertain, or open-ended reasoning and actions."}
    choices.update({key: value.get("description", key) for key, value in actions.items()})
    if observation is not None and observation["return_result"] and not observation["truncated"]:
        choices["finish"] = "Return the observed tool result to the user without further elaboration."
    offered_actions = deepcopy(actions)
    roles = {}
    if iteration == 0:
        try:
            from usr.plugins.auxiliary_model_roles.helpers.runtime import available_roles
            roles = available_roles(agent)
        except ImportError:
            pass
        if policy.get("action_precedence") == "tool_first" and "tool" in roles:
            state["complete"] = True
            finish_main_step(agent, "Delegated to Tool", detail="Tool role has precedence")
            return delegation_action("tool", text)
        for role in roles:
            choices[f"specialist_{role}"] = f"Delegate a bounded {role} task to the configured specialist."
    if len(choices) < 2:
        state["complete"] = True
        finish_main_step(agent, "Handed off to Main", detail="No eligible choices")
        return None
    try:
        client = client_for(section, policy)
        max_state = _bounded_int(policy.get("max_state_chars"), 4000, 256, 16_000)
        decision_state = text
        if observation is not None:
            original = text[:max_state // 2]
            decision_state = (f"Original request: {original}\n"
                              f"Prior action: {observation['tool_name']}\n"
                              f"Observed result: {observation['result'] or '[result content withheld by policy]'}")
        result = await client.choose(decision_state[:max_state], choices)
        if _turn_state(agent) is not state:
            state["complete"] = True
            finish_main_step(agent, "Handed off to Main", detail="Request changed during decision")
            return None
        latest = config_for(agent, "main")
        if not latest:
            state["complete"] = True
            finish_main_step(agent, "Handed off to Main", detail="Mode disabled during decision")
            return None
        policy = latest[1]
        actions = allowed_actions(policy)
        threshold = float(policy.get("min_choice_probability", 0.85))
        if (result.backend != "chat" and result.choice == "finish" and
                observation is not None and result.confidence >= threshold):
            prior = actions.get(observation["action_id"], {})
            if (observation["return_result"] and not observation["truncated"] and
                    prior == observation["action_definition"] and
                    prior.get("return_result_to_user") is True):
                state["complete"] = True
                finish_main_step(agent, "Finished from observed result", confidence=result.confidence)
                return json.dumps({"tool_name": "response", "tool_args": {
                    "text": observation["return_result"]}}, separators=(",", ":"))
        if iteration == 0 and result.choice.startswith("specialist_") and result.confidence >= threshold:
            role = result.choice.removeprefix("specialist_")
            try:
                from usr.plugins.auxiliary_model_roles.helpers.runtime import available_roles
                current_roles = available_roles(agent)
            except ImportError:
                current_roles = {}
            if role in current_roles:
                state["complete"] = True
                finish_main_step(agent, f"Delegated to {role.title()}",
                                 confidence=result.confidence)
                return delegation_action(role, text)
        current_limit = _bounded_int(policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS)
        action = None
        if (result.backend != "chat" and result.choice not in state["used_action_ids"]
                and state["actions_submitted"] < current_limit
                and result.choice in offered_actions
                and actions.get(result.choice) == offered_actions[result.choice]):
            action = selected_action(result, actions, threshold=threshold)
        if action:
            selected = actions[result.choice]
            state["actions_submitted"] += 1
            state["used_action_ids"].add(result.choice)
            state["pending"] = {
                "action_id": result.choice, "tool_name": action["tool_name"],
                "action_definition": deepcopy(selected),
                "share_result": selected.get("share_result_with_backend") is True,
                "return_result": selected.get("return_result_to_user") is True,
                "result_limit": _bounded_int(policy.get("max_result_chars"), 2000, 1, _MAX_RESULT_CHARS),
            }
            finish_main_step(agent, "Selected eligible action",
                             confidence=result.confidence,
                             detail="Submitted to Agent Zero for normal execution",
                             action_name=action["tool_name"])
            return json.dumps(action, separators=(",", ":"))
        state["complete"] = True
        finish_main_step(agent, "Handed off to Main",
                         confidence=result.confidence,
                         detail="No eligible action met the policy")
    except (DecisionError, ValueError, TypeError, OSError):
        state["complete"] = True
        finish_main_step(agent, "Handed off to Main", detail="Decision unavailable")
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
