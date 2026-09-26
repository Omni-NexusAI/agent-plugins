"""Opt-in finite Utility responses with the host Utility model as fallback."""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import itertools
import json
import math
import re
import time

from usr.plugins.system_1.helpers.runtime import client_for, config_for


_METRICS = "_system_1_utility_metrics"
_MAX_RESPONSE_CHARS = 4000
_MAX_DIRECT_QUERY_CHARS = 512
_MAX_MEMORY_CANDIDATES = 6
_MAX_MEMORY_CANDIDATE_CHARS = 4000
_MAX_MEMORY_CALL_CHARS = 12000
_INITIAL_BOOTSTRAP_RECORD_CHARS = 545
_INITIAL_BOOTSTRAP_RECORD_SHA256 = (
    "eea58c02cbaef35f0411521f92b18e523b5ad95bd8da82b56c6996dd7ca36a9d"
)

# Normalized copies of the Agent Zero _memory prompts verified against the
# current host source. A host prompt edit is deliberately ineligible until its
# full shape is reviewed here.
MEMORY_QUERY_SYSTEM = """# AI's job
1. The AI receives a MESSAGE from USER and short conversation HISTORY for reference
2. AI analyzes the MESSAGE and HISTORY for CONTEXT
3. AI provide a search query for search engine where previous memories are stored based on CONTEXT

# Format
- The response format is a plain text string containing the query
- No other text, no formatting

# No query
- If the conversation is not relevant for memory search, return a single dash (-)

# Rules
- Only focus on facts and events, ignore common conversation patterns, greeting etc.
- Ignore AI thoughts and behavior
- Focus on USER MESSAGE if provided, use HISTORY for context

# Ignored:
For the following topics, no query is needed and return a single dash (-):
- Greeting

# Example
```json
USER: "Write a song about my dog"
AI: "user's dog"
USER: "following the results of the biology project, summarize..."
AI: "biology project results"
```"""

MEMORY_FILTER_SYSTEM = """# AI's job
1. The AI receives enumerated list of MEMORIES, a MESSAGE from USER and short conversation HISTORY for context
2. AI analyzes the relationship between MEMORIES and MESSAGE+HISTORY
3. AI evaluates which memories are relevant and helpful for the current situation
4. AI provides an array of indices of relevant memories and solutions for current situation

# Format
- The response format is a json array of integers corresponding to memory indices
- No other text, intro, explanation, formatting

# Rules:
- The end of the message history is more recent and thus more relevant
- Focus on USER MESSAGE if provided, use HISTORY for context
- Keep in mind that these memories should be helpful for continuing the conversation and solving problems by AI
- Consider if each memory holds real information value for the context or not
- If memories include timestamps, treat recency as a soft signal: newer/current memories are usually better for mutable facts, while old durable facts may still be useful
- If multiple memories conflict about the same mutable user/project fact, include only the newest/current one when it is identifiable
- Exclude superseded, historical, duplicate, or low-detail fragments when a more complete current memory is available

# Include only when:
- Memory is relevant to the current situation
- Memory contains helpful facts that can be used

# Never include:
- Short vague texts like "Pet inquiry" or "Programming skills" with no more detail
- Common conversation patterns like greetings
- Memories that hold no information value
- Older conflicting memories for the same preference or project state when a newer/current memory is available

# Example output
```json
[0, 2]
```

# Examples of memories that are never relevant (with explanation)
> "User has greeted me" (no information value)
> "Hello world program" (just title, no details, no context, irrelevant by itself)
> "Today is Monday" (just date, information obsolete, not helpful)
> "Memory search" (just title, irrelevant by itself)"""

MEMORY_SUMMARY_SYSTEM = """# Assistant's job
1. The assistant receives a HISTORY of conversation between USER and AGENT
2. Assistant searches for relevant information from the HISTORY worth memorizing
3. Assistant writes notes about information worth memorizing for further use

# Format
- The response format is a JSON array of text notes containing facts to memorize
- If the history does not contain any useful information, the response will be an empty JSON array.

# Output example
~~~json
[
  "User's name is John Doe",
  "User's dog's name is Max",
]
~~~

# Rules
- Only memorize complete information that is helpful in the future
- Never memorize vague or incomplete information
- Never memorize keywords or titles only
- Focus only on relevant details and facts like names, IDs, events, opinions etc.
- Do not include irrelevant details that are of no use in the future
- Do not memorize facts that change like time, date etc.
- Do not add your own details that are not specifically mentioned in the history
- Do not memorize AI's instructions or thoughts

# Merging and cleaning
- The goal is to keep the number of new memories low while making memories more complete and detailed
- Do not break information related to the same subject into multiple memories, keep them as one text
- If there are multiple facts related to the same subject, merge them into one more detailed memory instead
- Example: Instead of three memories "User's dog is Max", "Max is 6 years old", "Max is white and brown", create one memory "User's dog is Max, 6 years old, white and brown."

# Correct examples of data worth memorizing with (explanation)
> User's name is John Doe (name is important)
> AsyncRaceError in primary_modules.py was fixed by adding a thread lock on line 123 (important event with details for context)
> Local SQL database was created, server is running on port 3306 (important event with details for context)

# WRONG examples with (explanation of error), never output memories like these
> Dog Information (no useful facts)
> The user requested current RAM and CPU status. (No exact facts to memorize)
> User greeted with 'hi' (just conversation, not useful in the future )
> Respond with a warm greeting and invite further conversation (do not memorize AI's instructions or thoughts)
> User's name (details missing, not useful)
> Today is Monday (just date, no value in this information)
> Market inquiry (just a topic without detail)
> RAM Status (just a topic without detail)


# Further WRONG examples
- Hello"""

# SHA-256 of normalized current Agent Zero built-in _memory system prompts.
# Fixed responses must never substitute an open-ended host memory operation.
_PROTECTED_MEMORY_SYSTEM_DIGESTS = frozenset({
    "242bb160cfe71600a35326f833c5c4ad2c0c56e8ba2f7f834d7cc4f70d2d4e73",
    "4c40b63c0fb58f9de3b96a4abfa5aa1c3b6b0431611dfca4d94b8f145c9d6339",
    "530719b5c7eebf36acf7f3dfa4024373e992016ba15cfae8570f5e4b86c2455d",
    "f8b0304eaa752154762c528bbfd7eae3c84c7af1b98ee09052bec87aeed2a430",
    "51a5c88bf0370794e2290b553bf91ad72a42d0a5ba4c3875e7022e08addaac9f",
    "c920bf29d1b70e706ce80cf44cbfa98f5305c554511a106c40ec03c96af75fb4",
    "6b515dd42b5f5066399599c6848182f49ffea5c0897984a3202b4ec5a92538e8",
    "1f4c169e9383bb6c58e625f2ca8271007058fe593ea0a2273069d813d5f917bf",
    "dbfd31280683d62c6a1a3c78fe04fa029cb898d4e42abfe7a2970e2637a292e7",
})
_MEMORY_INGESTION_SYSTEM_DIGESTS = frozenset({
    "242bb160cfe71600a35326f833c5c4ad2c0c56e8ba2f7f834d7cc4f70d2d4e73",
    "4c40b63c0fb58f9de3b96a4abfa5aa1c3b6b0431611dfca4d94b8f145c9d6339",
    "6b515dd42b5f5066399599c6848182f49ffea5c0897984a3202b4ec5a92538e8",
    "dbfd31280683d62c6a1a3c78fe04fa029cb898d4e42abfe7a2970e2637a292e7",
})


class UtilityRouteResult:
    """Whether an exact route was tried and whether it bypassed Utility."""

    __slots__ = ("attempted", "bypassed")

    def __init__(self, attempted: bool, bypassed: bool):
        self.attempted = attempted
        self.bypassed = bypassed

    def __bool__(self) -> bool:
        return self.bypassed


INELIGIBLE = UtilityRouteResult(False, False)
FALLBACK = UtilityRouteResult(True, False)
BYPASS = UtilityRouteResult(True, True)


def metrics(agent) -> dict:
    """Per-agent counters; no prompt, response, or credential is retained."""
    current = getattr(agent, _METRICS, None)
    if not isinstance(current, dict):
        current = {}
        setattr(agent, _METRICS, current)
    # Hot-loaded agents may have older counter dictionaries. Keep only counters
    # and timing aggregates here; request data and provider credentials never fit.
    for key, value in {
        "calls": 0, "decisions": 0, "bypassed": 0, "fallbacks": 0,
        "ordinary_generations": 0, "fallback_model_calls": 0,
        "decision_seconds": 0.0, "bypass_seconds": 0.0,
        "fallback_model_seconds": 0.0, "ordinary_model_seconds": 0.0,
    }.items():
        current.setdefault(key, value)
    current.setdefault("model_call_categories", {})
    current.setdefault("memory_filter_gate", {})
    return current


def metrics_snapshot(agent) -> dict:
    """Return a copy suitable for read-only status reporting."""
    return dict(metrics(agent))


def _threshold(policy: dict) -> float:
    value = float(policy.get("min_choice_probability", 0.85))
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Invalid Utility decision threshold")
    return value


def _match_route(section: dict, call_data: dict) -> dict | None:
    routes = section.get("fixed_routes", [])
    if not isinstance(routes, list) or len(routes) > 32:
        return None
    system, message = call_data.get("system"), call_data.get("message")
    if not isinstance(system, str) or not isinstance(message, str):
        return None
    matches = [route for route in routes if isinstance(route, dict)
               and route.get("system") == system and route.get("message") == message]
    if len(matches) != 1:
        return None
    route = matches[0]
    responses = route.get("responses")
    if (not isinstance(responses, dict) or not 1 <= len(responses) <= 254
            or any(not isinstance(key, str) or not key or key == "ordinary"
                   or not isinstance(value, str) or not value
                   or len(value) > _MAX_RESPONSE_CHARS
                   for key, value in responses.items())):
        return None
    return route


def _finite_backend(section: dict) -> bool:
    """Only finite-decision services may authorize a Utility bypass."""
    return section.get("backend") in {"jev", "openrouter", "llama_decision"}


def _decision_payload_fits(policy: dict, state: str, choices: dict) -> bool:
    """Reject a complete decision that cannot fit without truncating it."""
    try:
        limit = min(16000, max(1, int(policy.get("max_state_chars", 4000))))
    except (TypeError, ValueError, OverflowError):
        return False
    payload = json.dumps({"state": state, "choices": choices}, ensure_ascii=False)
    return len(payload.encode("utf-8")) <= limit


def _qualified_choice(decision, policy: dict, expected: set[str]) -> bool:
    confidence = getattr(decision, "confidence", None)
    return (getattr(decision, "choice", None) in expected
            and isinstance(confidence, (int, float))
            and math.isfinite(confidence)
            and 0 <= confidence <= 1
            and confidence >= _threshold(policy))


def _normalise_system(system: str) -> str:
    return "\n".join(line.rstrip() for line in system.replace("\r\n", "\n").split("\n")).strip()


def _system_digest(system: str) -> str:
    return hashlib.sha256(_normalise_system(system).encode("utf-8")).hexdigest()


def _is_protected_memory_system(system) -> bool:
    if not isinstance(system, str):
        return False
    normalized = _normalise_system(system)
    if _system_digest(normalized) in _PROTECTED_MEMORY_SYSTEM_DIGESTS:
        return True
    # Exact hashes authorize the built-in fast paths. This second, deliberately
    # restrictive check only protects a changed host memory template from a
    # configured fixed reply: it stays on the ordinary Utility path instead.
    lowered = normalized.casefold()
    if any(marker in lowered for marker in (
            "agent zero memory management", "memory consolidation",
            "memory keyword extraction")):
        return True
    return ("history of conversation" in lowered
            and ("# assistant's job" in lowered or "# ai's job" in lowered)
            and any(marker in lowered for marker in (
                "memor", "summary", "solution", "search query", "array of indices")))


def _memory_call_kind(call_data: dict) -> str | None:
    """Recognize only the current Agent Zero memory Utility call shapes."""
    if not isinstance(call_data, dict):
        return None
    system = call_data.get("system")
    message = call_data.get("message")
    if not isinstance(system, str) or not isinstance(message, str):
        return None
    normalized = _normalise_system(system)
    if normalized == MEMORY_QUERY_SYSTEM:
        return "query"
    if normalized == MEMORY_FILTER_SYSTEM:
        return "filter"
    return None


def _direct_query(request: str) -> str | None:
    """Use only a plainly stated current request as a deterministic query."""
    query = request.strip()
    if (not query or len(query) > _MAX_DIRECT_QUERY_CHARS
            or "\n" in query or "\r" in query
            or len(query.split()) > 32
            or query.startswith(("{", "["))):
        return None
    lowered = query.casefold().rstrip(".!?")
    if (lowered in {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay",
                    "yes", "no", "how are you", "who are you", "what can you do"}
            or lowered.startswith(("hi ", "hello ", "hey ", "good morning", "good evening"))
            or re.search(r"\b(what about|other one|that one|this one|as above|previous|earlier|"
                         r"follow[- ]?up)\b", lowered)):
        return None
    return query


def _current_user_envelope(value: str, label: str) -> str | None:
    """Decode one complete, sanitized Agent Zero current-user history record."""
    value = value.strip()
    prefix = f"{label}:"
    if not value.startswith(prefix):
        return None
    raw = value[len(prefix):].strip()
    if not raw or "\n" in raw or "\r" in raw:
        return None
    try:
        envelope = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if (not isinstance(envelope, dict)
            or set(envelope) - {"user_message", "system_message", "attachments"}
            or not isinstance(envelope.get("user_message"), str)
            or any(envelope.get(key) not in (None, [], "")
                   for key in ("system_message", "attachments"))):
        return None
    return envelope["user_message"]


def _direct_host_request(request: str) -> str | None:
    """Extract a direct query from the structured current-user request when present."""
    request = request.strip()
    if request.startswith("user:"):
        current = _current_user_envelope(request, "user")
        return _direct_query(current) if current is not None else None
    return _direct_query(request)


def _known_bootstrap_then_current(history: str, current: str) -> bool:
    """Allow only the pinned host greeting record before the first user entry."""
    if len(history) <= _INITIAL_BOOTSTRAP_RECORD_CHARS:
        return False
    bootstrap = history[:_INITIAL_BOOTSTRAP_RECORD_CHARS]
    if hashlib.sha256(bootstrap.encode("utf-8")).hexdigest() != _INITIAL_BOOTSTRAP_RECORD_SHA256:
        return False
    remainder = history[_INITIAL_BOOTSTRAP_RECORD_CHARS:]
    if not remainder.startswith("\nuser:"):
        return False
    user_record = remainder[1:]
    # The verified host history renderer terminates this record with one LF.
    # Do not strip arbitrary whitespace or allow another history record.
    if user_record.endswith("\n"):
        user_record = user_record[:-1]
    if user_record != user_record.strip():
        return False
    return _current_user_envelope(user_record, "user") == current


def _query_request(message: str) -> str | None:
    """Parse Agent Zero's current query-preparation prompt without guessing."""
    prefix = "# Provide search query for the following:\n\n## User message:\n"
    history_marker = "\n\n## Conversation history for context:\n"
    if not message.startswith(prefix) or len(message) > _MAX_MEMORY_CALL_CHARS:
        return None
    request, marker, history = message[len(prefix):].partition(history_marker)
    if not marker or "\n\n## " in request:
        return None
    # Both the request and History.output_text() use a `user:` record in this
    # host. A fresh Agent Zero chat may precede the current history record with
    # the one pinned initial greeting. No other AI, tool, or prior record fits.
    if request.strip().startswith("user:"):
        current = _current_user_envelope(request, "user")
        if current is None:
            return None
        if history.strip() and (_current_user_envelope(history, "user") != current
                                and not _known_bootstrap_then_current(history, current)):
            return None
        return _direct_query(current)
    if history.strip():
        return None
    return _direct_host_request(request)


def _memory_filter_input(message: str, reason_out: dict | None = None
                         ) -> tuple[str, str, list[str]] | None:
    """Parse the host's bounded Python-dict candidate prompt without guessing."""
    def reject(reason: str):
        if reason_out is not None:
            reason_out["reason"] = reason
        return None

    prefix = ("# Provide array of indices of relevant memories and solutions in relation "
              "to user message and history:\n\n## Memories and solutions:\n")
    request_marker = "\n\n## User message:\n"
    history_marker = "\n\n## History for context:\n"
    if not message.startswith(prefix):
        return reject("template")
    if len(message) > _MAX_MEMORY_CALL_CHARS:
        return reject("message_length")
    raw_candidates, marker, remaining = message[len(prefix):].partition(request_marker)
    if not marker:
        return reject("template")
    request, marker, history = remaining.partition(history_marker)
    if not marker or "\n\n## " in request:
        return reject("template")
    try:
        values = ast.literal_eval(raw_candidates)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return reject("candidate_format")
    if not isinstance(values, dict):
        return reject("candidate_format")
    if not 1 <= len(values) <= _MAX_MEMORY_CANDIDATES:
        return reject("candidate_count")
    if (any(type(key) is not int for key in values)
            or set(values) != set(range(len(values)))):
        return reject("candidate_format")
    candidates = [values[index] for index in range(len(values))]
    if any(not isinstance(value, str) or not value.strip()
           for value in candidates):
        return reject("candidate_format")
    if any(len(value) > _MAX_MEMORY_CANDIDATE_CHARS for value in candidates):
        return reject("candidate_length")
    current_request = _direct_host_request(request)
    return (current_request, history, candidates) if current_request else reject("request_shape")


def _subset_choices(candidates: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Build finite relevance choices and their JSON index-list response."""
    choices, responses = {}, {}
    for size in range(len(candidates) + 1):
        for selected in itertools.combinations(range(len(candidates)), size):
            response = json.dumps(list(selected), separators=(",", ":"))
            choice_id = "keep_" + ("_".join(map(str, selected)) if selected else "none")
            choices[choice_id] = f"Return exactly this JSON index list: {response}"
            responses[choice_id] = response
    return choices, responses


class MeasuredUtilityModel:
    """Transparent host-model wrapper used only to time a verified call shape."""

    def __init__(self, original, agent, outcome: str, category: str):
        self.original, self.agent, self.outcome = original, agent, outcome
        self.category = category

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def unified_call(self, **kwargs):
        start = time.monotonic()
        try:
            return await self.original.unified_call(**kwargs)
        finally:
            record = metrics(self.agent)
            elapsed = max(0.0, time.monotonic() - start)
            _record_model_call(record, self.category, elapsed)
            if self.outcome == "fallback":
                record["fallback_model_calls"] += 1
                record["fallback_model_seconds"] += elapsed
            else:
                record["ordinary_generations"] += 1
                record["ordinary_model_seconds"] += elapsed


def utility_call_category(call_data: dict) -> str:
    """Classify a host call before Embedding guidance changes its system text."""
    purpose = _embedding_memory_purpose(call_data)
    return {
        "memory retrieval query preparation": "memory_query",
        "memory retrieval filtering": "memory_filter",
        "memory ingestion": "memory_ingestion",
    }.get(purpose, "other")


def _record_model_call(record: dict, category_name: str, elapsed: float) -> None:
    categories = record["model_call_categories"]
    category = categories.setdefault(category_name, {"calls": 0, "seconds": 0.0})
    category["calls"] += 1
    category["seconds"] += elapsed


def install_utility_measurement(agent, call_data: dict, *, outcome: str,
                                category: str | None = None) -> bool:
    """Measure a verified host Utility call without retaining its content."""
    if (not isinstance(call_data, dict)
            or not isinstance(call_data.get("system"), str)
            or not isinstance(call_data.get("message"), str)):
        return False
    original = call_data.get("model")
    if not callable(getattr(original, "unified_call", None)):
        return False
    if category not in {"memory_query", "memory_filter", "memory_ingestion", "other"}:
        category = utility_call_category(call_data)
    call_data["model"] = MeasuredUtilityModel(original, agent, outcome, category)
    return True


class FixedUtilityModel:
    """Use the fixed result only if the host still sends the matched request."""

    def __init__(self, original, system: str, message: str, response: str,
                 section: dict, confidence: float, agent):
        self.original = original
        self.system = system
        self.message = message
        self.response = response
        self.section = section
        self.confidence = confidence
        self.agent = agent
        self.category = utility_call_category({"system": system, "message": message})

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def unified_call(self, *, system_message: str, user_message: str,
                           response_callback=None, **kwargs):
        try:
            current = config_for(self.agent, "utility")
        except Exception:
            current = None
        if (system_message != self.system or user_message != self.message
                or not current or current[0] != self.section
                or not self._confidence_still_qualifies(current[1])):
            start = time.monotonic()
            try:
                return await self.original.unified_call(
                    system_message=system_message, user_message=user_message,
                    response_callback=response_callback, **kwargs)
            finally:
                result = metrics(self.agent)
                result["fallbacks"] += 1
                result["fallback_model_calls"] += 1
                elapsed = max(0.0, time.monotonic() - start)
                result["fallback_model_seconds"] += elapsed
                _record_model_call(result, self.category, elapsed)
        start = time.monotonic()
        try:
            if response_callback:
                await response_callback(self.response, self.response)
            return self.response, ""
        finally:
            result = metrics(self.agent)
            result["bypassed"] += 1
            result["bypass_seconds"] += max(0.0, time.monotonic() - start)

    def _confidence_still_qualifies(self, policy: dict) -> bool:
        try:
            return self.confidence >= _threshold(policy)
        except (TypeError, ValueError, OverflowError):
            return False


async def install_fixed_utility_response(agent, call_data: dict) -> UtilityRouteResult:
    """Install a guarded fixed response for an exact, explicitly configured call."""
    try:
        settings = config_for(agent, "utility")
    except Exception:
        return INELIGIBLE
    if not settings or not isinstance(call_data, dict) or "model" not in call_data:
        return INELIGIBLE
    if _is_protected_memory_system(call_data.get("system")):
        return INELIGIBLE
    section, policy = settings
    # Chat confidence is self-reported and cannot authorize a direct response.
    if not _finite_backend(section):
        return INELIGIBLE
    route = _match_route(section, call_data)
    if route is None:
        return INELIGIBLE
    try:
        route = deepcopy(route)
        section_snapshot = deepcopy(section)
        message = call_data["message"]
        system = call_data["system"]
        if not message:
            return INELIGIBLE
        choices = {"ordinary": "Use the original Utility model."}
        choices.update({key: f"Return this exact configured response: {value}"
                        for key, value in route["responses"].items()})
        decision_state = f"System instruction: {system}\nUser message: {message}"
        if not _decision_payload_fits(policy, decision_state, choices):
            return INELIGIBLE
        record = metrics(agent)
        record["decisions"] += 1
        start = time.monotonic()
        try:
            decision = await client_for(section, policy).choose(decision_state, choices)
        finally:
            record["decision_seconds"] += max(0.0, time.monotonic() - start)
        # Recheck mutable configuration and request after the remote decision.
        current = config_for(agent, "utility")
        if (not current or current[0] != section_snapshot
                or _match_route(current[0], call_data) != route
                or call_data["system"] != system or call_data["message"] != message
                or not _qualified_choice(decision, current[1], set(route["responses"]))):
            record["fallbacks"] += 1
            return FALLBACK
        call_data["model"] = FixedUtilityModel(
            call_data["model"], system, message,
            route["responses"][decision.choice], section_snapshot,
            decision.confidence, agent)
        return BYPASS
    except Exception:
        metrics(agent)["fallbacks"] += 1
        return FALLBACK


async def install_memory_utility_response(agent, call_data: dict) -> UtilityRouteResult:
    """Bypass only bounded memory query/filter call shapes with finite choices.

    Memory ingestion, summaries, title generation, complex query construction,
    and changed host prompts intentionally remain on the original Utility path.
    """
    kind = _memory_call_kind(call_data)
    if kind is None:
        return INELIGIBLE
    try:
        settings = config_for(agent, "utility")
    except Exception:
        return INELIGIBLE
    if not settings or not _finite_backend(settings[0]) or "model" not in call_data:
        return INELIGIBLE
    section, policy = settings
    system, message = call_data["system"], call_data["message"]
    gate = None
    if kind == "filter":
        gate = metrics(agent)["memory_filter_gate"]
        gate["seen"] = gate.get("seen", 0) + 1
    try:
        section_snapshot = deepcopy(section)
        if kind == "query":
            response = _query_request(message)
            if response is None:
                return INELIGIBLE
            choices = {
                "direct": "Return the exact direct search query shown in the state.",
                "ordinary": "Use the original Utility model to construct the query.",
            }
            decision_state = ("Current request is an unambiguous direct memory search.\n"
                              f"Direct search query: {response}")
            expected = {"direct"}
        else:
            reason_out = {}
            filter_input = _memory_filter_input(message, reason_out)
            if filter_input is None:
                gate["shape_ineligible"] = gate.get("shape_ineligible", 0) + 1
                reason = reason_out.get("reason", "template")
                key = "reason_" + reason
                gate[key] = gate.get(key, 0) + 1
                return INELIGIBLE
            current_request, history, candidates = filter_input
            choices, responses = _subset_choices(candidates)
            response = None
            decision_state = ("Select the relevant memory candidate indices only.\n"
                              f"Current request: {current_request}\n"
                              f"Conversation history: {history}\n" + "\n".join(
                                  f"Candidate {index}: {candidate}"
                                  for index, candidate in enumerate(candidates)))
            expected = set(responses)
        if not _decision_payload_fits(policy, decision_state, choices):
            if gate is not None:
                gate["payload_oversize"] = gate.get("payload_oversize", 0) + 1
            return INELIGIBLE
        record = metrics(agent)
        record["decisions"] += 1
        if gate is not None:
            gate["decision_attempted"] = gate.get("decision_attempted", 0) + 1
        started = time.monotonic()
        try:
            decision = await client_for(section, policy).choose(decision_state, choices)
        finally:
            record["decision_seconds"] += max(0.0, time.monotonic() - started)
        current = config_for(agent, "utility")
        stale = (not current or current[0] != section_snapshot
                 or _memory_call_kind(call_data) != kind
                 or call_data["system"] != system or call_data["message"] != message)
        qualified = not stale and _qualified_choice(decision, current[1], expected)
        if not qualified:
            record["fallbacks"] += 1
            if gate is not None:
                gate["fallback"] = gate.get("fallback", 0) + 1
                reason = ("stale" if stale else
                          "choice" if getattr(decision, "choice", None) not in expected
                          else "confidence")
                key = "reason_" + reason
                gate[key] = gate.get(key, 0) + 1
            return FALLBACK
        if kind == "filter":
            response = responses[decision.choice]
        call_data["model"] = FixedUtilityModel(
            call_data["model"], system, message, response, section_snapshot,
            decision.confidence, agent)
        if gate is not None:
            gate["bypass_installed"] = gate.get("bypass_installed", 0) + 1
        return BYPASS
    except Exception:
        metrics(agent)["fallbacks"] += 1
        if gate is not None:
            gate["fallback"] = gate.get("fallback", 0) + 1
            gate["reason_error"] = gate.get("reason_error", 0) + 1
        return FALLBACK


def _embedding_memory_purpose(call_data: dict) -> str | None:
    kind = _memory_call_kind(call_data)
    if kind == "query":
        return "memory retrieval query preparation"
    if kind == "filter":
        return "memory retrieval filtering"
    system = call_data.get("system") if isinstance(call_data, dict) else None
    if isinstance(system, str) and _system_digest(system) in _MEMORY_INGESTION_SYSTEM_DIGESTS:
        return "memory ingestion"
    return None


async def install_embedding_memory_guidance(agent, call_data: dict) -> bool:
    """Apply bounded Embedding-mode advice without changing the vector producer.

    The host still invokes its selected Utility model and performs every memory
    search or write. This only appends conservative provenance guidance after
    the Utility direct-response eligibility check has finished.
    """
    purpose = _embedding_memory_purpose(call_data)
    if purpose is None or not isinstance(call_data, dict):
        return False
    system, message = call_data.get("system"), call_data.get("message")
    if not isinstance(system, str) or not isinstance(message, str) or not message.strip():
        return False
    try:
        settings = config_for(agent, "embedding")
    except Exception:
        return False
    if not settings:
        return False
    section, policy = settings
    choices = {
        "normal": f"Use normal {purpose} with the configured embedding model.",
        "precise": (f"Use precise {purpose}; preserve facts, provenance, and the "
                    "complete host memory operation."),
    }
    state = f"Memory operation: {purpose}\nHost Utility request:\n{message}"
    if not _decision_payload_fits(policy, state, choices):
        return False
    try:
        snapshot = deepcopy(section)
        record = metrics(agent)
        record["decisions"] += 1
        started = time.monotonic()
        try:
            decision = await client_for(section, policy).choose(state, choices)
        finally:
            record["decision_seconds"] += max(0.0, time.monotonic() - started)
        current = config_for(agent, "embedding")
        if (not current or current[0] != snapshot
                or call_data.get("system") != system or call_data.get("message") != message
                or not _qualified_choice(decision, current[1], {"precise"})):
            return False
        call_data["system"] = (
            system + "\nSystem 1 embedding guidance: Preserve facts, provenance, and "
            "the relevant current context. The host embedding model and memory index "
            "remain authoritative.")
        return True
    except Exception:
        return False
