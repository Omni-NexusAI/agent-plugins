"""Agent Zero glue for looped mode.

Host modules are imported inside functions so this file loads on both host
generations (``call_chat_model`` returning a tuple, and ``call_chat_model_turn``
returning an ``LLMResult``) and in tests without a host.

Every hook entry point here contains its own errors: a looped-mode failure
must leave the agent's normal step untouched.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import weakref
from typing import Any

from .command import ARM_KEY, MODE_KEY
from .looped_core import (Metrics, StepContext, TurnState, merge_config, parse_step,
                          resolve_step, salvage_step)
from .looped_core.config import MODES
from .looped_core.controller import effective_mode, is_active
from .looped_core.prompts import RETRY_NOTE
from .looped_core.sampling import variant_params
from .looped_core.strategies import plan_branch, reread, retry

log = logging.getLogger("looped")

PLUGIN = "looped"
MAIN_CALL = "looped_main_call"     # set per iteration for the loop's own call
EARLY = "looped_early"             # a second sample started alongside the first
OVERRIDE = "looped_override"       # winner text when it replaced the first
SAW_REASONING = "_looped_saw_reasoning"
_EARLY_DELAY = 0.05                # let the host's own call reach the server first
_MAX_METRICS = 256

_states: "weakref.WeakKeyDictionary[Any, TurnState]" = weakref.WeakKeyDictionary()
_metrics: dict[str, Metrics] = {}

OUTCOMES = {
    "agreed": "both passes agree",
    "tiebreak": "passes disagreed, third pass decided",
    "no_majority": "three passes disagreed, kept the first",
    "disagreed_kept_first": "passes disagreed, kept the first",
    "only_valid": "first pass was invalid, used the second",
    "second_invalid": "second pass was invalid, kept the first",
    "both_invalid": "both passes were invalid",
    "second_unavailable": "second pass failed, kept the first",
    "fused": "merged two drafts of the answer",
    "fuse_failed": "merge failed, kept the first draft",
    "confirmed": "second pass confirmed the draft",
    "revised": "second pass revised the draft",
    "reasoned": "quick passes were unsure, used the reasoned pass",
    "reasoned_same": "quick passes were unsure, reasoning confirmed the first",
    "reasoning_unusable": "quick passes were unsure, the reasoned pass was unusable",
    "unsure_no_budget": "quick passes were unsure, no budget left to reason",
}


# --- configuration and per-chat state -------------------------------------

def config(agent: Any) -> dict[str, Any]:
    saved = None
    try:
        from helpers import plugins
        saved = plugins.get_plugin_config(PLUGIN, agent=agent)
    except Exception:
        log.debug("looped: plugin config unavailable, using defaults", exc_info=True)
    return merge_config(saved)


def chat_data(agent: Any) -> dict[str, Any]:
    data = getattr(getattr(agent, "context", None), "data", None)
    return data if isinstance(data, dict) else {}


def chat_mode(agent: Any) -> str | None:
    value = chat_data(agent).get(MODE_KEY)
    return value if value in MODES else None


def state(agent: Any) -> TurnState:
    try:
        return _states[agent]
    except KeyError:
        fresh = TurnState()
        _states[agent] = fresh
        return fresh


def applies(agent: Any, cfg: dict[str, Any]) -> bool:
    return getattr(agent, "number", 0) == 0 or cfg["apply_to_subordinates"]


def metrics_for(agent: Any) -> Metrics:
    key = str(getattr(getattr(agent, "context", None), "id", "") or "")
    if key not in _metrics:
        while len(_metrics) >= _MAX_METRICS:
            _metrics.pop(next(iter(_metrics)))
        _metrics[key] = Metrics()
    return _metrics[key]


def metrics_report(context_id: str) -> dict[str, Any]:
    found = _metrics.get(str(context_id or ""))
    return found.to_dict() if found else Metrics().to_dict()


def message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("user_message", "message", "text"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def is_thinking(agent: Any) -> bool:
    """True once this chat's model has been seen returning reasoning text."""
    return bool(chat_data(agent).get(SAW_REASONING))


# --- model access ----------------------------------------------------------

def host_parser(text: str) -> dict[str, Any] | None:
    """Strict parse, then the host's own tolerant parser, then the core's salvage.

    The host's parser goes before the salvage because it keeps the step's
    other fields (thoughts, headline) when it can read them.
    """
    parsed = parse_step(text, salvage=False)
    if parsed is not None:
        return parsed
    try:
        from helpers import extract_tools
        for name in ("extract_tool_request", "json_parse_dirty"):
            parser = getattr(extract_tools, name, None)
            value = parser(text) if parser else None
            if isinstance(value, dict):
                return value
    except Exception:
        pass
    return salvage_step(text)


async def extra_call(agent: Any, cfg: dict[str, Any], messages: list[Any],
                     variant: int, extra: str | None = None) -> tuple[str, str]:
    """Run the same prompt again without streaming. ``messages`` is copied:
    the host's model wrapper appends to the list it is given."""
    batch = list(messages)
    if extra:
        from langchain_core.messages import HumanMessage
        batch.append(HumanMessage(content=extra))
    model = agent.get_chat_model()
    params = variant_params(cfg, variant)
    try:
        response, reasoning = await model.unified_call(messages=list(batch), **params)
    except asyncio.CancelledError:
        raise
    except Exception:
        if not params:
            raise
        # A provider that rejects seed/temperature overrides still gets one try.
        response, reasoning = await model.unified_call(messages=list(batch))
    return response or "", reasoning or ""


async def plain_call(agent: Any, cfg: dict[str, Any], system: str, user: str,
                     variant: int) -> str:
    model = agent.get_chat_model()
    response, _ = await model.unified_call(
        system_message=system, user_message=user, **variant_params(cfg, variant))
    return response or ""


# --- hook entry points -----------------------------------------------------

def begin_turn(agent: Any) -> None:
    try:
        _states[agent] = TurnState(armed=bool(chat_data(agent).get(ARM_KEY)))
    except Exception:
        log.exception("looped: could not start turn state")


def end_turn(agent: Any) -> None:
    try:
        if getattr(agent, "number", 0) == 0:
            chat_data(agent).pop(ARM_KEY, None)
    except Exception:
        log.exception("looped: could not clear the one-shot arm")


def mark_main_call(agent: Any, loop_data: Any) -> None:
    params = getattr(loop_data, "params_temporary", None)
    if isinstance(params, dict):
        params[MAIN_CALL] = True


async def on_prompt(agent: Any, loop_data: Any) -> None:
    """Add the re-read block, the retry note and, once, the merged plan."""
    try:
        cfg = config(agent)
        current = state(agent)
        if not applies(agent, cfg) or not is_active(cfg, current, chat_mode(agent)):
            return
        task = message_text(getattr(loop_data, "user_message", None))
        block = reread.build(task, cfg, thinking=is_thinking(agent))
        if block:
            loop_data.extras_temporary["looped_reread"] = block
        if current.retry_armed and cfg["strategies"]["retry"]["enabled"]:
            loop_data.extras_temporary["looped_retry"] = RETRY_NOTE
        if getattr(loop_data, "iteration", 0) <= 0:
            async def plain(system: str, user: str, variant: int) -> str:
                return await plain_call(agent, cfg, system, user, variant)
            note = await plan_branch.build(task, plain, cfg, current)
            if note:
                loop_data.extras_persistent["looped_plan"] = note
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("looped: prompt hook failed; prompt left unchanged")


def _main_call(agent: Any, data: dict[str, Any]) -> tuple[dict[str, Any], list[Any]] | None:
    """Return the iteration params and messages when this is the loop's own call."""
    params = getattr(getattr(agent, "loop_data", None), "params_temporary", None)
    if not isinstance(params, dict) or not params.get(MAIN_CALL):
        return None
    kwargs = data.get("kwargs") if isinstance(data.get("kwargs"), dict) else {}
    args = data.get("args") if isinstance(data.get("args"), tuple) else ()
    messages = kwargs.get("messages", args[1] if len(args) > 1 else None)
    background = kwargs.get("background", args[4] if len(args) > 4 else False)
    if background or not isinstance(messages, list):
        return None
    return params, messages


async def on_call_start(agent: Any, data: dict[str, Any]) -> None:
    """In parallel execution, start the second sample alongside the first."""
    try:
        found = _main_call(agent, data)
        if not found:
            return
        params, messages = found
        cfg = config(agent)
        current = state(agent)
        strategies = cfg["strategies"]
        every_step = current.armed or effective_mode(cfg, chat_mode(agent)) == "always"
        if (cfg["execution"] != "parallel" or not applies(agent, cfg)
                or not is_active(cfg, current, chat_mode(agent)) or not every_step
                or strategies["deepen"]["enabled"] or not strategies["agree"]["enabled"]
                or current.remaining(cfg) <= 0
                or cfg["budget"]["max_extra_calls_per_step"] <= 0):
            return
        snapshot = list(messages)

        async def early() -> tuple[str, str]:
            await asyncio.sleep(_EARLY_DELAY)
            return await extra_call(agent, cfg, snapshot, 1)
        params[EARLY] = asyncio.ensure_future(early())
    except Exception:
        log.exception("looped: could not start the parallel sample")


def _unpack(result: Any, turn: bool) -> tuple[str | None, str]:
    if not turn:
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], str):
            return result[0], result[1] if isinstance(result[1], str) else ""
        return None, ""
    response = getattr(result, "response", None)
    if not isinstance(response, str):
        return None, ""
    for item in getattr(result, "output_items", None) or []:
        # Native function calls (Responses transport) are not text steps.
        if getattr(item, "type", "") == "function_call":
            return None, ""
    reasoning = getattr(result, "reasoning", "")
    return response, reasoning if isinstance(reasoning, str) else ""


def _repack(result: Any, text: str, reasoning: str, turn: bool) -> Any:
    if not turn:
        return text, reasoning
    from helpers.llm_result import LLMResult
    try:
        return LLMResult.from_chat(
            response=text, reasoning=reasoning,
            usage=getattr(result, "usage", None),
            provider_model_key=getattr(result, "provider_model_key", ""),
            capability=getattr(result, "capability", None),
            finish_reason=getattr(result, "finish_reason", ""))
    except TypeError:
        return LLMResult.from_chat(response=text, reasoning=reasoning)


def _log_decision(agent: Any, decision: Any, cfg: dict[str, Any]) -> None:
    show = cfg["show_steps"]
    if show == "none" or (show == "changed" and not decision.changed):
        return
    try:
        candidates = "; ".join(
            f"{item.label}: {item.kind}" + (f" {item.tool_name}" if item.tool_name else "")
            for item in decision.candidates)
        agent.context.log.log(
            type="info",
            heading=f"Looped: {OUTCOMES.get(decision.outcome, decision.outcome)}",
            content="",
            kvps={"checkpoint": decision.reason, "strategy": decision.strategy,
                  "used": decision.winner.label, "passes": candidates,
                  "extra_calls": decision.extra_calls,
                  "elapsed": f"{decision.elapsed:.1f}s"})
    except Exception:
        log.debug("looped: could not write the timeline step", exc_info=True)


async def on_call_end(agent: Any, data: dict[str, Any], turn: bool) -> None:
    """Classify the loop's own step and, at a checkpoint, look twice."""
    found = None
    early = None
    try:
        found = _main_call(agent, data)
        if not found:
            return
        params, messages = found
        params.pop(MAIN_CALL, None)
        early = params.pop(EARLY, None)
        if isinstance(data.get("exception"), BaseException):
            return
        result = data.get("result")
        response, reasoning = _unpack(result, turn)
        if response is None:
            return
        cfg = config(agent)
        if not applies(agent, cfg):
            return
        if reasoning.strip():
            chat_data(agent)[SAW_REASONING] = True
        loop_data = agent.loop_data
        snapshot = list(messages)

        async def sample(variant: int) -> tuple[str, str]:
            return await extra_call(agent, cfg, snapshot, variant)

        async def ask(text: str, variant: int) -> tuple[str, str]:
            return await extra_call(agent, cfg, snapshot, variant, extra=text)

        reasoning_params = cfg["strategies"]["escalate"]["reasoning_params"]

        async def think() -> tuple[str, str]:
            # No fallback to a call without the options: that would be a third
            # quick sample, not a reasoned one.
            model = agent.get_chat_model()
            answer, thought = await model.unified_call(
                messages=list(snapshot), **copy.deepcopy(reasoning_params))
            return answer or "", thought or ""

        ctx = StepContext(cfg=cfg, state=state(agent), sample=sample, ask=ask,
                          last_response=getattr(loop_data, "last_response", None) or None,
                          parser=host_parser, early_second=early,
                          think=think if reasoning_params else None)
        early = None
        decision = await resolve_step(response, reasoning,
                                      getattr(loop_data, "iteration", 0),
                                      ctx, chat_mode(agent))
        metrics_for(agent).record(decision)
        if decision.strategy == "none":
            return
        _log_decision(agent, decision, cfg)
        winner = decision.winner
        if decision.changed and isinstance(winner.parsed, dict):
            text = json.dumps(winner.parsed, ensure_ascii=False)
            data["result"] = _repack(result, text, winner.reasoning or reasoning, turn)
            params[OVERRIDE] = text
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("looped: step check failed; the original step is used")
    finally:
        if early is not None:
            early.cancel()


async def on_stream_end(agent: Any, loop_data: Any) -> None:
    """Show the winning step in the chat when it replaced the streamed one."""
    try:
        params = getattr(loop_data, "params_temporary", None)
        text = params.pop(OVERRIDE, None) if isinstance(params, dict) else None
        if text:
            await agent.handle_response_stream(text)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.debug("looped: could not refresh the streamed step", exc_info=True)


def on_tool_result(agent: Any, response: Any) -> None:
    try:
        cfg = config(agent)
        current = state(agent)
        if applies(agent, cfg) and is_active(cfg, current, chat_mode(agent)):
            retry.note_tool_result(getattr(response, "message", None), cfg, current)
    except Exception:
        log.exception("looped: tool result hook failed")
