"""Constrain a cloned model's request, never reinterpret an answer or tool result."""
from copy import deepcopy

ENVELOPE = {
    "type": "object",
    "properties": {
        "thoughts": {"type": "array", "items": {"type": "string"}},
        "headline": {"type": "string"},
        "tool_name": {"type": "string"},
        "tool_args": {"type": "object", "additionalProperties": True},
    },
    "required": ["thoughts", "headline", "tool_name", "tool_args"],
    "additionalProperties": False,
}


def prepare_model(model, config):
    """Only an explicit supported OpenRouter Chat Completions opt-in may clone."""
    if not isinstance(config, dict) or not isinstance(config.get("models"), list):
        return model
    allowed = config["models"]
    if not all(isinstance(x, str) and x.startswith("openrouter/") for x in allowed):
        return model
    if getattr(model, "provider", None) != "openrouter" or getattr(model, "model_name", None) not in allowed:
        return model
    source = getattr(model, "kwargs", None)
    copy_model = getattr(model, "model_copy", None)
    if not isinstance(source, dict) or not callable(copy_model):
        return model
    if ("response_format" in source or source.get("tools") or "tool_choice" in source
            or source.get("a0_api_mode") not in (None, "chat", "chat_completions")):
        return model
    extra = source.get("extra_body", {})
    if not isinstance(extra, dict) or not isinstance(extra.get("provider", {}), dict):
        return model
    if ("response_format" in extra or extra.get("tools") or "tool_choice" in extra
            or isinstance(source.get("text"), dict) and "format" in source["text"]
            or isinstance(extra.get("text"), dict) and "format" in extra["text"]):
        return model
    kwargs = deepcopy(source)
    kwargs["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": "agent_zero_tool_envelope", "strict": True, "schema": deepcopy(ENVELOPE)},
    }
    kwargs.setdefault("extra_body", {}).setdefault("provider", {})["require_parameters"] = True
    return copy_model(update={"kwargs": kwargs}, deep=False)
