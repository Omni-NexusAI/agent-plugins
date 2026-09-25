"""Guarded adapter between finite System 1 choices and Agent Zero calls."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
import re
from urllib.parse import urlsplit

from helpers import plugins
from usr.plugins.system_1.helpers.system_1_core import DecisionClient, DecisionError
from usr.plugins.system_1.helpers.system_1_core.decision import selected_action
from usr.plugins.system_1.helpers.timeline import finish_main_step
from usr.plugins.system_1.helpers.tool_availability import is_tool_available


PLUGIN = "system_1"
_TURN_STATE = "_system_1_action_turn"
_MAX_ACTIONS = 8
_MAX_RESULT_CHARS = 4000
_DECIDER_FIELDS = ("backend", "provider", "model", "endpoint", "token_env", "context_window")


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
             "observations": [],
             "main_task": None, "main_started_actions": -1,
             "main_requested": False, "main_guidance": "", "main_snapshot": None}
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
        "binding_result": (result[:limit] if pending["bind_result"] else ""),
    }
    state["observations"].append(state["observation"])
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

    if len(decision_state) > 4000:
        return None

    detached = getattr(agent, "_system_1_detached_main_calls", None)
    if isinstance(detached, set) and any(not task.done() for task in detached):
        return None  # Do not accumulate uncancellable provider calls across turns.

    instruction = ("Reason about the uncertain part of this Agent Zero request. "
                   "System 1 may independently use tools while you think. Do not call tools, "
                   "claim tool execution, or assume newer tool results. Return only a JSON "
                   "object with kind 'correction' and concise text guiding subsequent "
                   "System 1 choices, or kind 'final' and text for a final response when "
                   "no further tool result is needed.")
    messages = [SystemMessage(content=instruction),
                HumanMessage(content=decision_state)]
    call = asyncio.create_task(agent.call_chat_model(
        messages=messages, background=True, explicit_caching=False))
    try:
        done, _ = await asyncio.wait({call}, timeout=timeout)
        if not done:
            _detach_main_call(agent, call)
            return None
        if call.cancelled():
            return None
        response, _ = call.result()
        parsed = json.loads(response)
        if not isinstance(parsed, dict) or parsed.get("kind") not in {"correction", "final"}:
            return None
        answer = parsed.get("text")
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 4000:
            return None
        return {"kind": parsed["kind"], "text": answer.strip()}
    except asyncio.CancelledError:
        _detach_main_call(agent, call)
        raise
    except Exception:
        return None


def _detach_main_call(agent, task: asyncio.Task) -> None:
    """Retain at most one uncancellable call until it actually exits."""
    detached = getattr(agent, "_system_1_detached_main_calls", None)
    if not isinstance(detached, set):
        detached = set()
        setattr(agent, "_system_1_detached_main_calls", detached)
    detached.add(task)
    task.cancel()

    def discard(done: asyncio.Task) -> None:
        detached.discard(done)
        if not done.cancelled():
            try:
                done.exception()
            except Exception:
                pass

    task.add_done_callback(discard)


def _take_main_result(agent, state: dict) -> dict | None:
    task = state.get("main_task")
    if not isinstance(task, asyncio.Task) or not task.done():
        return None
    state["main_task"] = None
    if task.cancelled():
        return None
    try:
        result = task.result()
        return result if config_for(agent, "main") == state["main_snapshot"] else None
    except Exception:
        return None


def _consume_main_result(state: dict, result: dict | None) -> str:
    if not isinstance(result, dict):
        return ""
    if result.get("kind") == "correction":
        state["main_guidance"] = result["text"]
    elif (result.get("kind") == "final" and
          state["actions_submitted"] == state["main_started_actions"]):
        return result["text"]
    # A final drafted before later System 1 actions cannot be committed as-is.
    return ""


def main_handoff_note(agent) -> str:
    """Give foreground Main a bounded account of this turn's host observations.

    The normal host history remains the source of tool arguments and results.
    This note contains neither result contents nor request text, and is never
    added for background advice or a later user turn.
    """
    state = _turn_state(agent)
    if not state or not state["complete"] or not state["observations"]:
        return ""
    settings = config_for(agent, "main")
    if not settings:
        return ""
    actions = allowed_actions(settings[1])
    names = []
    for observation in state["observations"][:_MAX_ACTIONS]:
        if (actions.get(observation["action_id"]) != observation["action_definition"]
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", observation["tool_name"])):
            return ""
        names.append(observation["tool_name"])
    return ("System 1 continuation for this user request: Agent Zero already "
            f"executed {len(names)} selected tool call(s): {', '.join(names)}. "
            "Their observed results are in the normal tool history. Use that "
            "evidence before choosing another tool. Do not repeat an already "
            "recorded call unless its evidence is insufficient; a different "
            "argument or a genuine follow-up may require a new call. Complete "
            "the remaining reasoning and give the user a clear final answer. "
            "Do not return raw tool data as the final answer.")


def delegation_action(role: str, goal: str) -> str:
    return json.dumps({"tool_name": "auxiliary_delegate", "tool_args": {
        "role": role, "goal": goal[:8000]}}, separators=(",", ":"))


def migrate_decider_config(config: dict) -> dict:
    """Copy a compatible legacy connection to Decider without losing role settings.

    Only enabled roles participate in conflict detection. Disabled legacy
    defaults remain in place for rollback but never override the shared slot.
    If two enabled roles disagree, preserve the old per-role behavior until a
    user explicitly chooses the shared connection in the settings UI.
    """
    migrated = deepcopy(config)
    if not isinstance(config, dict) or isinstance(config.get("decider"), dict):
        return migrated
    sections = [config.get(name) for name in ("main", "utility", "embedding")]
    active = [item for item in sections if isinstance(item, dict) and item.get("enabled")]
    candidates = active or [item for item in sections if isinstance(item, dict)]
    connections = [{key: item[key] for key in _DECIDER_FIELDS if key in item}
                   for item in candidates]
    if connections and connections[0] and all(item == connections[0] for item in connections):
        migrated["decider"] = deepcopy(connections[0])
    return migrated


def config_for(agent, section: str) -> tuple[dict, dict] | None:
    config = plugins.get_plugin_config(PLUGIN, agent)
    if not isinstance(config, dict):
        return None
    config = migrate_decider_config(config)
    section_config = config.get(section)
    if not isinstance(section_config, dict) or not section_config.get("enabled"):
        return None
    decider = config.get("decider")
    if isinstance(decider, dict):
        section_config = deepcopy(section_config)
        for key in _DECIDER_FIELDS:
            section_config.pop(key, None)
        section_config.update({key: deepcopy(decider[key]) for key in _DECIDER_FIELDS
                               if key in decider})
    return section_config, config.get("policy", {}) if isinstance(config.get("policy"), dict) else {}


def bound_decision_state(state: str, choices: dict, context_window) -> str:
    """Fail closed if a complete decision cannot fit the configured window.

    Trimming can remove a Main correction, observed tool result, or exact Utility
    request and cause a decision based on incomplete state.
    """
    if context_window in (None, "", 0):
        return state
    try:
        window = int(context_window)
    except (TypeError, ValueError, OverflowError) as error:
        raise DecisionError("Invalid Decider context window") from error
    if not 1024 <= window <= 1_000_000:
        raise DecisionError("Invalid Decider context window")
    reserved = len(json.dumps(choices, ensure_ascii=False).encode("utf-8")) + 512
    available = window - reserved
    if available < 1:
        raise DecisionError("Decider choices exceed context window")
    if not state.strip() or len(state.encode("utf-8")) > available:
        raise DecisionError("Decider state exceeds context window")
    return state


class ContextBoundClient:
    def __init__(self, inner, context_window):
        self.inner, self.context_window = inner, context_window

    async def choose(self, state: str, choices: dict):
        return await self.inner.choose(
            bound_decision_state(state, choices, self.context_window), choices)


def client_for(section_config: dict, policy: dict) -> DecisionClient:
    backend = section_config.get("backend", "")
    token_env = section_config.get("token_env", "")
    if backend == "openrouter":
        token_env = "API_KEY_OPENROUTER"
    token = os.environ.get(token_env, "") if isinstance(token_env, str) and token_env else ""
    if backend in {"jev", "openrouter"} and not token:
        raise DecisionError(f"{backend} key is unavailable")
    if backend == "chat":
        inner = ChatDecisionClient(section_config, policy)
    else:
        inner = DecisionClient(backend=backend,
                               model=section_config.get("model", ""),
                               endpoint=section_config.get("endpoint", ""), token=token,
                               timeout=float(policy.get("timeout_seconds", 2)))
    return ContextBoundClient(inner, section_config.get("context_window"))


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
                "api_base": self.section_config.get("endpoint", ""),
                "ctx_length": self.section_config.get("context_window") or 0}
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
            and isinstance(value.get("tool_args"), dict)
            and (value["tool_args"] or value.get("argument_bindings"))
            and isinstance(value.get("description", key), str)}


def _validated_scalar(value, binding: dict):
    """Accept only bounded primitive values constrained by a configured validator."""
    if type(value) not in (str, int, bool):
        return None
    rendered = str(value) if type(value) is not bool else str(value).lower()
    if not rendered or len(rendered) > _bounded_int(binding.get("max_chars"), 256, 1, 1024):
        return None
    kind = binding.get("value_type")
    if kind == "enum":
        allowed = binding.get("allowed_values")
        if (not isinstance(allowed, list) or not 1 <= len(allowed) <= 100 or
                any(type(item) not in (str, int, bool) for item in allowed) or
                not any(type(value) is type(item) and value == item for item in allowed)):
            return None
    elif kind == "integer":
        if not rendered.isascii() or not rendered.isdecimal() or len(rendered) > 18:
            return None
        value = int(rendered)
    elif kind == "slug":
        if (rendered in {".", ".."} or not rendered.isascii() or
                not all(char.isalnum() or char in "_-." for char in rendered)):
            return None
    elif kind == "github_repo":
        owner, separator, repo = rendered.partition("/")
        if (not separator or "/" in repo or not owner or not repo or
                not all(char.isascii() and (char.isalnum() or char in "_-") for char in owner) or
                not all(char.isascii() and (char.isalnum() or char in "_.-") for char in repo)):
            return None
    elif kind == "https_url":
        hosts = binding.get("allowed_hosts")
        if not isinstance(hosts, list) or not hosts or len(hosts) > 20:
            return None
        try:
            parsed = urlsplit(rendered)
            valid_url = (parsed.scheme == "https" and bool(parsed.hostname) and
                         parsed.hostname in hosts and not parsed.username and
                         not parsed.password and parsed.port in (None, 443))
        except (TypeError, ValueError):
            valid_url = False
        if not valid_url:
            return None
    else:
        return None
    return value


def _binding_value(binding: dict, request: str, observations: list):
    source = binding.get("source")
    if source == "request":
        prefix, suffix = binding.get("prefix"), binding.get("suffix")
        if (not isinstance(prefix, str) or not isinstance(suffix, str) or
                len(prefix) + len(suffix) > 512 or not (prefix or suffix)):
            return None
        if (len(request) > 4000 or not request.startswith(prefix) or
                not request.endswith(suffix) or len(request) <= len(prefix) + len(suffix)):
            return None
        value = request[len(prefix):len(request) - len(suffix) if suffix else len(request)]
    elif source == "result":
        action_id = binding.get("from_action")
        path = binding.get("path")
        if (not isinstance(action_id, str) or not isinstance(path, list) or
                not 1 <= len(path) <= 8):
            return None
        prior = next((item for item in reversed(observations)
                      if item["action_id"] == action_id), None)
        if not prior or not prior["binding_result"] or prior["truncated"]:
            return None
        try:
            value = json.loads(prior["binding_result"])
            for component in path:
                if isinstance(value, dict) and isinstance(component, str):
                    value = value[component]
                elif isinstance(value, list) and type(component) is int and 0 <= component < len(value):
                    value = value[component]
                else:
                    return None
        except (ValueError, TypeError, KeyError, IndexError):
            return None
    else:
        return None
    return _validated_scalar(value, binding)


def _resolved_action(definition: dict, request: str, observations: list) -> dict | None:
    """Bind declared fields only; never accept model-created tool arguments."""
    arguments = deepcopy(definition["tool_args"])
    bindings = definition.get("argument_bindings", {})
    if not isinstance(bindings, dict):
        return None
    for key, binding in bindings.items():
        if not isinstance(key, str) or not key or not isinstance(binding, dict):
            return None
        if key in arguments:
            return None
        value = _binding_value(binding, request, observations)
        if value is None:
            return None
        arguments[key] = value
    if not arguments:
        return None
    return {"tool_name": definition["tool_name"], "tool_args": arguments}


def _eligible_actions(agent, policy: dict, state: dict, request: str,
                      *, independent_only: bool = False) -> dict:
    limit = _bounded_int(policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS)
    if state["actions_submitted"] >= limit:
        return {}
    definitions = allowed_actions(policy)
    observations = _safe_binding_observations(state, definitions)
    return {key: value for key, value in definitions.items()
            if key not in state["used_action_ids"]
            and (not independent_only or value.get("independent_while_main") is True)
            and is_tool_available(agent, value["tool_name"])
            and _resolved_action(value, request, observations) is not None}


def _safe_binding_observations(state: dict, definitions: dict) -> list:
    observations = []
    for observed in state["observations"]:
        current = definitions.get(observed["action_id"])
        safe = dict(observed)
        if (current != observed["action_definition"] or not current or
                current.get("allow_result_bindings") is not True):
            safe["binding_result"] = ""
        observations.append(safe)
    return observations


def _decision_state(text: str, observations: list, policy: dict,
                     max_state: int, guidance: str) -> str:
    """Recheck result-sharing consent before every post-await backend choice."""
    state = text
    if observations:
        events = []
        for observation in observations:
            prior = allowed_actions(policy).get(observation["action_id"])
            shared = (observation["result"] if prior == observation["action_definition"]
                      and prior.get("share_result_with_backend") is True else "")
            events.append(f"Prior choice: {observation['action_id']}\n"
                          f"Prior action: {observation['tool_name']}\n"
                          f"Observed result: {shared or '[result content withheld by policy]'}")
        state = f"Original request: {text}\n" + "\n".join(events)
    if guidance:
        state += "\nMain correction: " + guidance
    if len(state) > max_state:
        raise DecisionError("Complete Main decision state exceeds policy limit")
    return state


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
    if state["main_guidance"] and settings != state["main_snapshot"]:
        _complete(state)
        finish_main_step(agent, "Handed off to Main", detail="Main correction became stale")
        return None
    text = agent.last_user_message.output_text() if agent.last_user_message else ""
    if not text.strip():
        _complete(state)
        finish_main_step(agent, "Handed off to Main", detail="No request text")
        return None
    observation = state["observation"]
    if observation is not None:
        state["observation"] = None
        current_prior = allowed_actions(policy).get(observation["action_id"])
        if current_prior != observation["action_definition"]:
            observation["result"] = ""
            observation["return_result"] = ""
        advisory_done = (isinstance(state["main_task"], asyncio.Task) and
                         state["main_task"].done())
        final_text = _consume_main_result(state, _take_main_result(agent, state))
        if final_text:
            _complete(state)
            finish_main_step(agent, "Main supplied final response")
            return json.dumps({"tool_name": "response", "tool_args": {
                "text": final_text}}, separators=(",", ":"))
        if advisory_done and state["main_requested"] and not state["main_guidance"]:
            _complete(state)
            finish_main_step(agent, "Handed off to Main",
                             detail="Main advisory did not resolve the uncertain work")
            return None
    main_pending = isinstance(state["main_task"], asyncio.Task) and not state["main_task"].done()
    actions = _eligible_actions(agent, policy, state, text,
                                independent_only=main_pending)
    choices = {"main": "Use Main for complex, uncertain, or open-ended reasoning and actions."}
    choices.update({key: value.get("description", key) for key, value in actions.items()})
    if (observation is not None and observation["return_result"] and
            "." not in observation["tool_name"] and
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
            final_text = _consume_main_result(state, _take_main_result(agent, state))
            if final_text:
                _complete(state)
                finish_main_step(agent, "Main supplied final response")
                return json.dumps({"tool_name": "response", "tool_args": {
                    "text": final_text}}, separators=(",", ":"))
            if state["main_guidance"]:
                latest_policy = config_for(agent, "main")[1]
                policy = latest_policy
                current_limit = _bounded_int(
                    latest_policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS)
                actions = _eligible_actions(agent, latest_policy, state, text)
                choices.update({key: value.get("description", key) for key, value in actions.items()})
                offered_actions = deepcopy(actions)
        if len(choices) < 2:
            _complete(state)
            detail = ("Main advisory applied; no eligible choices" if state["main_guidance"]
                      else "Main advisory unavailable; remaining work handed to Main"
                      if state["main_requested"] else "No eligible choices")
            finish_main_step(agent, "Handed off to Main", detail=detail)
            return None
    try:
        client = client_for(section, policy)
        max_state = _bounded_int(policy.get("max_state_chars"), 4000, 256, 16_000)
        decision_state = _decision_state(text, state["observations"], policy, max_state,
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
        if state["main_guidance"] and latest != state["main_snapshot"]:
            _complete(state)
            finish_main_step(agent, "Handed off to Main", detail="Main correction became stale")
            return None
        policy = latest[1]
        actions = allowed_actions(policy)
        threshold = float(policy.get("min_choice_probability", 0.85))
        if (result.backend != "chat" and result.choice == "finish" and
                observation is not None and result.confidence >= threshold):
            prior = actions.get(observation["action_id"], {})
            if (observation["return_result"] and not observation["truncated"] and
                    "." not in observation["tool_name"] and
                    prior == observation["action_definition"] and
                    prior.get("return_result_to_user") is True):
                _complete(state)
                finish_main_step(agent, "Finished from observed result", confidence=result.confidence)
                return json.dumps({"tool_name": "response", "tool_args": {
                    "text": observation["return_result"]}}, separators=(",", ":"))
        if result.choice == "main" and result.backend != "chat":
            # Main joins only when Jev flagged uncertainty. While it thinks,
            # Jev may choose another action explicitly marked independent.
            decision_state = _decision_state(text, state["observations"], policy, max_state,
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
                    state["main_snapshot"] = deepcopy(config_for(agent, "main"))
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
                    if result.choice == "wait_main":
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
                        final_text = _consume_main_result(state, _take_main_result(agent, state))
                        if final_text:
                            _complete(state)
                            finish_main_step(agent, "Main supplied final response")
                            return json.dumps({"tool_name": "response", "tool_args": {
                                "text": final_text}}, separators=(",", ":"))
                        if state["main_guidance"]:
                            corrected_policy = config_for(agent, "main")[1]
                            corrected_state = _decision_state(
                                text, state["observations"], corrected_policy, max_state,
                                state["main_guidance"])
                            corrected_limit = _bounded_int(
                                corrected_policy.get("max_actions_per_turn"), 3, 1, _MAX_ACTIONS)
                            corrected_available = _eligible_actions(
                                agent, corrected_policy, state, text)
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
                    if state["main_guidance"] and latest != state["main_snapshot"]:
                        _complete(state)
                        finish_main_step(agent, "Handed off to Main", detail="Main correction became stale")
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
            current = _eligible_actions(agent, policy, state, text,
                                        independent_only=main_pending and not state["main_guidance"])
            if current.get(result.choice) == offered_actions[result.choice]:
                resolved = _resolved_action(
                    current[result.choice], text,
                    _safe_binding_observations(state, actions))
                if resolved:
                    action = selected_action(result, {result.choice: resolved}, threshold=threshold)
        if action:
            selected = actions[result.choice]
            state["actions_submitted"] += 1
            state["used_action_ids"].add(result.choice)
            state["pending"] = {
                "action_id": result.choice, "tool_name": action["tool_name"],
                "action_definition": deepcopy(selected),
                "share_result": selected.get("share_result_with_backend") is True,
                "bind_result": selected.get("allow_result_bindings") is True,
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
        detail = (("Main correction applied; decision confidence below action threshold"
                   if state["main_guidance"] else "Decision confidence below action threshold")
                  if result.choice in offered_actions and result.confidence < threshold else
                  "Main correction applied; no eligible action met the policy"
                  if state["main_guidance"] else
                  "No eligible action met the policy")
        finish_main_step(agent, "Handed off to Main",
                         confidence=result.confidence,
                         detail=detail)
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
