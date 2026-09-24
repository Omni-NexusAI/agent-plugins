"""Guarded adapter between finite System 1 choices and Agent Zero calls."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os

from helpers import plugins
from usr.plugins.system_1.helpers.system_1_core import DecisionClient, DecisionError
from usr.plugins.system_1.helpers.system_1_core.decision import selected_action
from usr.plugins.system_1.helpers.timeline import finish_main_step
from usr.plugins.system_1.helpers.tool_availability import is_tool_available


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
    if isinstance(state, dict):
        _cancel_main_task(state)
    state = {"loop_data": loop_data, "user_message": user_message,
             "attempted_iteration": -1,
             "actions_submitted": 0, "used_action_ids": set(),
             "pending": None, "observation": None, "complete": False,
             "main_task": None, "main_started_actions": -1,
             "main_requested": False, "main_guidance": ""}
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
        _cancel_main_task(raw_state)
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


def _cancel_main_task(state: dict) -> None:
    task = state.get("main_task")
    if isinstance(task, asyncio.Task) and not task.done():
        try:
            task.cancel()
        except RuntimeError:
            # The host can end a monologue after its event loop has closed.
            pass
    state["main_task"] = None


def _complete(state: dict) -> None:
    state["complete"] = True
    _cancel_main_task(state)


def end_turn(agent) -> None:
    """Cancel plugin-owned advisory work when the host ends this monologue."""
    state = getattr(agent, _TURN_STATE, None)
    if isinstance(state, dict):
        _complete(state)


async def _run_main_correction(agent, decision_state: str, timeout: float) -> dict | None:
    """Get advisory text from Main without tool execution or history writes."""
    from langchain_core.messages import HumanMessage, SystemMessage

    instruction = ("Reason about the uncertain part of this Agent Zero request. "
                   "System 1 may independently use tools while you think. Do not call tools, "
                   "claim tool execution, or assume newer tool results. Return only a JSON "
                   "object with kind 'correction' and concise text guiding subsequent "
                   "System 1 choices, or kind 'final' and text for a final response when "
                   "no further tool result is needed.")
    messages = [SystemMessage(content=instruction),
                HumanMessage(content=decision_state[:4000])]
    try:
        response, _ = await asyncio.wait_for(agent.call_chat_model(
            messages=messages, background=True, explicit_caching=False), timeout)
        parsed = json.loads(response)
        if not isinstance(parsed, dict) or parsed.get("kind") not in {"correction", "final"}:
            return None
        answer = parsed.get("text")
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 4000:
            return None
        return {"kind": parsed["kind"], "text": answer.strip()}
    except (OSError, ValueError, TypeError, TimeoutError, KeyError):
        return None


def _take_main_result(state: dict) -> dict | None:
    task = state.get("main_task")
    if not isinstance(task, asyncio.Task) or not task.done():
        return None
    state["main_task"] = None
    if task.cancelled():
        return None
    try:
        return task.result()
    except Exception:
        return None


def _consume_main_result(state: dict, result: dict | None) -> str:
    if not isinstance(result, dict):
        return ""
    if result.get("kind") == "correction":
        state["main_guidance"] = result["text"][:2000]
    elif (result.get("kind") == "final" and
          state["actions_submitted"] == state["main_started_actions"]):
        return result["text"]
    # A final drafted before later System 1 actions cannot be committed as-is.
    return ""


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
            if isinstance(key, str) and key not in {"", "main", "finish", "wait_main"}
            and not key.startswith("specialist_") and isinstance(value, dict)
            and isinstance(value.get("tool_name"), str)
            and isinstance(value.get("tool_args"), dict) and value["tool_args"]
            and isinstance(value.get("description", key), str)}


def _decision_state(text: str, observation: dict | None, policy: dict,
                    max_state: int, guidance: str) -> str:
    """Recheck result-sharing consent before every post-await backend choice."""
    state = text
    if observation is not None:
        prior = allowed_actions(policy).get(observation["action_id"])
        shared = (observation["result"] if prior == observation["action_definition"]
                  else "")
        state = (f"Original request: {text[:max_state // 2]}\n"
                 f"Prior action: {observation['tool_name']}\n"
                 f"Observed result: {shared or '[result content withheld by policy]'}")
    if guidance:
        guidance_budget = max(32, max_state // 3)
        state = (state[:max_state - guidance_budget] +
                 "\nMain correction: " + guidance[:guidance_budget - 18])
    return state[:max_state]


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
        _complete(state)
        finish_main_step(agent, "Handed off to Main", detail="Mode disabled")
        return None
    section, policy = settings
    text = agent.last_user_message.output_text() if agent.last_user_message else ""
    if not text.strip():
        _complete(state)
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
        advisory_done = (isinstance(state["main_task"], asyncio.Task) and
                         state["main_task"].done())
        _consume_main_result(state, _take_main_result(state))
        if advisory_done and state["main_requested"] and not state["main_guidance"]:
            _complete(state)
            finish_main_step(agent, "Handed off to Main",
                             detail="Main advisory did not resolve the uncertain work")
            return None
    main_pending = isinstance(state["main_task"], asyncio.Task) and not state["main_task"].done()
    actions = {key: value for key, value in allowed_actions(policy).items()
               if key not in state["used_action_ids"] and
               (not main_pending or value.get("independent_while_main") is True) and
               is_tool_available(agent, value["tool_name"])}
    if state["actions_submitted"] >= limit:
        actions = {}
    choices = {"main": "Use Main for complex, uncertain, or open-ended reasoning and actions."}
    choices.update({key: value.get("description", key) for key, value in actions.items()})
    if (observation is not None and observation["return_result"] and
            not observation["truncated"] and not main_pending and
            (not state["main_requested"] or bool(state["main_guidance"]))):
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
            _complete(state)
            finish_main_step(agent, "Delegated to Tool", detail="Tool role has precedence")
            return delegation_action("tool", text)
        for role in roles:
            choices[f"specialist_{role}"] = f"Delegate a bounded {role} task to the configured specialist."
    if len(choices) < 2:
        task = state["main_task"]
        if isinstance(task, asyncio.Task):
            try:
                await task
            except asyncio.CancelledError:
                if _turn_state(agent) is state:
                    raise
            except Exception:
                pass
            if _turn_state(agent) is not state or not config_for(agent, "main"):
                _complete(state)
                finish_main_step(agent, "Handed off to Main", detail="Request or mode changed")
                return None
            _consume_main_result(state, _take_main_result(state))
            if state["main_guidance"]:
                latest_policy = config_for(agent, "main")[1]
                policy = latest_policy
                current_limit = _bounded_int(
                    latest_policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS)
                actions = {key: value for key, value in allowed_actions(latest_policy).items()
                           if key not in state["used_action_ids"] and
                           state["actions_submitted"] < current_limit and
                           is_tool_available(agent, value["tool_name"])}
                choices.update({key: value.get("description", key) for key, value in actions.items()})
                offered_actions = deepcopy(actions)
        if len(choices) < 2:
            _complete(state)
            detail = ("Main advisory applied; no eligible choices" if state["main_guidance"]
                      else "No eligible choices")
            finish_main_step(agent, "Handed off to Main", detail=detail)
            return None
    try:
        client = client_for(section, policy)
        max_state = _bounded_int(policy.get("max_state_chars"), 4000, 256, 16_000)
        decision_state = _decision_state(text, observation, policy, max_state,
                                         state["main_guidance"])
        result = await client.choose(decision_state, choices)
        if _turn_state(agent) is not state:
            _complete(state)
            finish_main_step(agent, "Handed off to Main", detail="Request changed during decision")
            return None
        latest = config_for(agent, "main")
        if not latest:
            _complete(state)
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
                _complete(state)
                finish_main_step(agent, "Finished from observed result", confidence=result.confidence)
                return json.dumps({"tool_name": "response", "tool_args": {
                    "text": observation["return_result"]}}, separators=(",", ":"))
        if result.choice == "main" and result.backend != "chat":
            # Main joins only when Jev flagged uncertainty. While it thinks,
            # Jev may choose another action explicitly marked independent.
            decision_state = _decision_state(text, observation, policy, max_state,
                                             state["main_guidance"])
            independent = {key: value for key, value in offered_actions.items()
                           if value.get("independent_while_main") is True and
                           actions.get(key) == value}
            if independent and state["actions_submitted"] < _bounded_int(
                    policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS):
                if not state["main_requested"]:
                    timeout = _bounded_int(policy.get("main_correction_seconds"), 12, 1, 30)
                    state["main_task"] = asyncio.create_task(
                        _run_main_correction(agent, decision_state, timeout))
                    state["main_requested"] = True
                    state["main_started_actions"] = state["actions_submitted"]
                task = state["main_task"]
                if isinstance(task, asyncio.Task):
                    concurrent_choices = {"wait_main": "Wait for Main's bounded correction or final response."}
                    concurrent_choices.update({key: value.get("description", key)
                                               for key, value in independent.items()})
                    result = await client.choose(decision_state, concurrent_choices)
                    if _turn_state(agent) is not state or not config_for(agent, "main"):
                        _complete(state)
                        finish_main_step(agent, "Handed off to Main", detail="Request or mode changed")
                        return None
                    if result.choice == "wait_main" or task.done():
                        if not task.done():
                            try:
                                await task
                            except asyncio.CancelledError:
                                if _turn_state(agent) is state:
                                    raise
                            except Exception:
                                pass
                        if _turn_state(agent) is not state or not config_for(agent, "main"):
                            _complete(state)
                            finish_main_step(agent, "Handed off to Main", detail="Request or mode changed")
                            return None
                        final_text = _consume_main_result(state, _take_main_result(state))
                        if final_text:
                            _complete(state)
                            finish_main_step(agent, "Main supplied final response")
                            return json.dumps({"tool_name": "response", "tool_args": {
                                "text": final_text}}, separators=(",", ":"))
                        if state["main_guidance"]:
                            corrected_policy = config_for(agent, "main")[1]
                            corrected_state = _decision_state(
                                text, observation, corrected_policy, max_state,
                                state["main_guidance"])
                            corrected_limit = _bounded_int(
                                corrected_policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS)
                            corrected_available = {
                                key: value for key, value in allowed_actions(corrected_policy).items()
                                if key not in state["used_action_ids"] and
                                state["actions_submitted"] < corrected_limit and
                                is_tool_available(agent, value["tool_name"])}
                            offered_actions = deepcopy(corrected_available)
                            corrected_choices = {"main": "Hand off to Main for the remaining work."}
                            corrected_choices.update({key: value.get("description", key)
                                                      for key, value in offered_actions.items()})
                            result = (await client.choose(corrected_state, corrected_choices)
                                      if len(corrected_choices) > 1 else None)
                        else:
                            result = None
                    else:
                        offered_actions = deepcopy(independent)
                    latest = config_for(agent, "main")
                    if _turn_state(agent) is not state or not latest:
                        _complete(state)
                        finish_main_step(agent, "Handed off to Main", detail="Request or mode changed")
                        return None
                    policy = latest[1]
                    actions = allowed_actions(policy)
                    threshold = float(policy.get("min_choice_probability", 0.85))
            # Without an independent eligible action, normal Main owns the
            # request immediately; no duplicate background call is started.
        if result is None or _turn_state(agent) is not state:
            _complete(state)
            finish_main_step(agent, "Handed off to Main", detail="Correction unavailable or request changed")
            return None
        if iteration == 0 and result.choice.startswith("specialist_") and result.confidence >= threshold:
            role = result.choice.removeprefix("specialist_")
            try:
                from usr.plugins.auxiliary_model_roles.helpers.runtime import available_roles
                current_roles = available_roles(agent)
            except ImportError:
                current_roles = {}
            if role in current_roles:
                _complete(state)
                finish_main_step(agent, f"Delegated to {role.title()}",
                                 confidence=result.confidence)
                return delegation_action(role, text)
        current_limit = _bounded_int(policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS)
        action = None
        if (result.backend != "chat" and result.choice not in state["used_action_ids"]
                and state["actions_submitted"] < current_limit
                and result.choice in offered_actions
                and actions.get(result.choice) == offered_actions[result.choice]
                and is_tool_available(agent, actions[result.choice]["tool_name"])):
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
                             detail=("Main correction applied; submitted to Agent Zero"
                                     if state["main_guidance"] else
                                     "Main advisory requested; submitted to Agent Zero"
                                     if state["main_requested"] else
                                     "Submitted to Agent Zero for normal execution"),
                             action_name=action["tool_name"])
            return json.dumps(action, separators=(",", ":"))
        _complete(state)
        finish_main_step(agent, "Handed off to Main",
                         confidence=result.confidence,
                         detail=("Main correction applied; no eligible action met the policy"
                                 if state["main_guidance"] else
                                 "No eligible action met the policy"))
    except (DecisionError, ValueError, TypeError, OSError):
        _complete(state)
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
