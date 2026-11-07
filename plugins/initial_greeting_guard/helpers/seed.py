"""Fail-closed, plugin-owned provenance for newly created native welcome turns.

No greeting keyword heuristics, native method replacement, or persisted-message
deletion. Historical unmarked seeds deliberately remain untouched.
"""
from functools import lru_cache
import hashlib
import inspect
import json
from pathlib import Path

KEY = "initial_greeting_guard"
ORIGIN = "native_initial_message"
SUPPORTED_INITIALIZERS = frozenset({
    "92dc7257efb2b78f1b0433c2f27bc4079208cca58635224c4a98253834c30561",
    "6f481bc1336f0ff03ba63813a4acc12658322ca4576ca59ce26d9af3c618c7df",
})


def _content_hash(content):
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=8)
def _trusted_source(code):
    if code.co_name != "execute" or code.co_qualname != "InitialMessage.execute":
        return None
    try:
        from helpers import files
        expected = Path(files.get_abs_path("extensions/python/agent_init/_10_initial_message.py")).resolve()
        actual = Path(code.co_filename).resolve()
        if actual != expected:
            return None
        digest = hashlib.sha256(actual.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return None
    return digest if digest in SUPPORTED_INITIALIZERS else None


def _initializer_origin(agent):
    frame = inspect.currentframe()
    try:
        for _ in range(48):
            frame = frame.f_back if frame is not None else None
            if frame is None:
                return None
            digest = _trusted_source(frame.f_code)
            owner = frame.f_locals.get("self")
            if digest and getattr(owner, "agent", None) is agent:
                return digest, frame.f_locals.get("initial_user_message"), frame.f_locals.get("initial_message")
    finally:
        del frame
    return None


def mark_created_pair(agent, message):
    """Called at native hist_add_message/end while the initializer is on-stack."""
    if agent is None or getattr(agent, "number", None) != 0:
        return False
    if not getattr(message, "ai", False) or getattr(message, "sequence", None) != 2:
        return False
    origin = _initializer_origin(agent)
    if origin is None or agent.context.log.logs:
        return False
    digest, user_text, assistant_text = origin
    records = agent.history.all_messages()
    if len(records) != 2 or records[1] is not message:
        return False
    user, assistant = records
    if user.ai or user.sequence != 1 or user.content != {"user_message": user_text}:
        return False
    trusted_metadata = {"initial_seed": True} if digest == "6f481bc1336f0ff03ba63813a4acc12658322ca4576ca59ce26d9af3c618c7df" else {}
    if user.metadata != trusted_metadata or assistant.content != assistant_text:
        return False
    from helpers.llm_result import LLMResult, metadata_from_llm_result
    if assistant.metadata != metadata_from_llm_result(LLMResult.non_llm()):
        return False
    if not user.id or not assistant.id or user.id == assistant.id:
        return False
    marker = {"schema": 1, "origin": ORIGIN, "source_sha256": digest,
              "user_id": user.id, "assistant_id": assistant.id,
              "user_content_sha256": _content_hash(user.content),
              "assistant_content_sha256": _content_hash(assistant.content)}
    user.metadata = {**user.metadata, KEY: {**marker, "role": "user"}}
    assistant.metadata = {**assistant.metadata, KEY: {**marker, "role": "assistant"}}
    return True


def model_history(records):
    """Return original list unless its first pair has matching provenance tags."""
    if len(records) < 3:
        return records
    user, assistant = records[:2]
    um = (user.get("metadata") or {}).get(KEY)
    am = (assistant.get("metadata") or {}).get(KEY)
    if not isinstance(um, dict) or not isinstance(am, dict):
        return records
    if user.get("ai") is not False or assistant.get("ai") is not True:
        return records
    if user.get("sequence") != 1 or assistant.get("sequence") != 2:
        return records
    if um.get("role") != "user" or am.get("role") != "assistant":
        return records
    expected = {"schema", "origin", "source_sha256", "user_id", "assistant_id", "role",
                "user_content_sha256", "assistant_content_sha256"}
    if set(um) != expected or set(am) != expected:
        return records
    common = {k: v for k, v in um.items() if k != "role"}
    if common != {k: v for k, v in am.items() if k != "role"}:
        return records
    if common.get("schema") != 1 or common.get("origin") != ORIGIN:
        return records
    if common.get("source_sha256") not in SUPPORTED_INITIALIZERS:
        return records
    if user.get("id") != common.get("user_id") or assistant.get("id") != common.get("assistant_id"):
        return records
    if not common.get("user_id") or not common.get("assistant_id") or common["user_id"] == common["assistant_id"]:
        return records
    if common["user_content_sha256"] != _content_hash(user.get("content")) or common["assistant_content_sha256"] != _content_hash(assistant.get("content")):
        return records
    # Never leave a leading AI message for the native serializer to drop.
    # Require an actual user-message record, not a warning or tool receipt.
    next_record = records[2]
    content = next_record.get("content")
    if next_record.get("ai") is not False or not isinstance(content, dict) or not content.get("user_message"):
        return records
    return records[2:]
