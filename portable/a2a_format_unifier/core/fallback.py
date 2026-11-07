"""Reply-only format adaptation after a native validator has rejected a reply."""
from copy import deepcopy

from .formats import FormatError, dialect_from_card, encode_result


def is_agent_zero(card):
    provider = card.get("provider") or {}
    if not isinstance(provider, dict):
        provider = {}
    name = str(card.get("name", "")).lower().replace(" ", "").replace("-", "")
    organization = str(provider.get("organization", "")).lower().replace(" ", "").replace("-", "")
    return organization == "agentzero" or name in ("agentzero", "a0")


def adapt_rejected_reply(response, card, native_validator):
    """No requests, dispatch, aliases or peer choice; validate the converted reply again."""
    if not isinstance(card, dict) or is_agent_zero(card):
        raise FormatError("Native Agent Zero replies are not adapted")
    if dialect_from_card(card) not in ("0.3", "1.0"):
        raise FormatError("Peer does not advertise a supported cross-framework format")
    if not isinstance(response, dict) or "error" in response or not isinstance(response.get("result"), dict):
        raise FormatError("Only a received successful A2A result can be adapted")
    converted = deepcopy(response)
    converted["result"] = encode_result(converted["result"], "0.3")
    return native_validator(converted)
