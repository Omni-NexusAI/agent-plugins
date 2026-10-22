"""Pure parsers that turn local inference server model lists into one normalized entry shape.

No network, no host imports. Every value that leaves this module is a sanitized string, a bounded integer
or a boolean: raw payload fragments (llama.cpp ``status.args`` / ``status.preset`` command lines, which can hold
``--api-key``) are inspected for a context size and a vision projector and then dropped.

Entry: {id, label, aliases[], state, failed, context{served, max, configured}, vision, kind, quant}
  state   one of STATES ("unknown" when the endpoint does not say)
  kind    "chat" | "embedding" | None   (only when the endpoint itself says so; never guessed from the name)
"""
from __future__ import annotations

import re
from typing import Any

STATES = ("loaded", "loading", "sleeping", "unloaded", "downloading", "incomplete", "downloaded", "unknown")
KIND_LABELS = {
    "llama_cpp_router": "llama.cpp router",
    "llama_cpp": "llama.cpp",
    "lm_studio": "LM Studio",
    "ollama": "Ollama",
    "llama_swap": "llama-swap",
    "unsloth": "Unsloth Studio",
    "strata_router": "Strata Router",
    "koboldcpp": "KoboldCpp",
    "tabbyapi": "TabbyAPI",
    "openai_compatible": "OpenAI-compatible server",
}
MAX_ENTRIES = 1000
MAX_TEXT = 512
MAX_CONTEXT = 10_000_000

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_STATE_ALIASES = {
    "ready": "loaded", "running": "loaded", "starting": "loading", "stopped": "unloaded", "stopping": "unloaded",
    "not-loaded": "unloaded", "not_loaded": "unloaded", "idle": "unloaded",
}
_EMBEDDING_WORDS = ("embedding", "embeddings", "embed", "rerank", "reranking")


# ---------------------------------------------------------------- primitives
def _text(value: Any, limit: int = MAX_TEXT) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned and len(cleaned) <= limit and not _CONTROL.search(cleaned):
            return cleaned
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and 1 <= value <= MAX_CONTEXT:
        return value
    return None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _state(value: Any) -> str:
    text = _text(value, 64)
    if not text:
        return "unknown"
    text = text.lower()
    text = _STATE_ALIASES.get(text, text)
    return text if text in STATES else "unknown"


def _rows(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "models"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def make_entry(model_id: Any, *, label: Any = None, aliases: Any = None, state: str = "unknown", failed: Any = None,
               served: Any = None, max_context: Any = None, configured: Any = None, vision: Any = None,
               kind: str | None = None, quant: Any = None) -> dict | None:
    ident = _text(model_id)
    if ident is None:
        return None
    alias_list: list[str] = []
    for alias in aliases if isinstance(aliases, list) else []:
        cleaned = _text(alias)
        if cleaned and cleaned != ident and cleaned not in alias_list:
            alias_list.append(cleaned)
    return {
        "id": ident,
        "label": _text(label),
        "aliases": alias_list[:20],
        "state": state if state in STATES else "unknown",
        "failed": bool(failed) if failed is not None else False,
        "context": {"served": _int(served), "max": _int(max_context), "configured": _int(configured)},
        "vision": _bool(vision),
        "kind": kind if kind in ("chat", "embedding") else None,
        "quant": _text(quant, 64),
    }


def _dedupe(entries: list[dict | None]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for entry in entries:
        if entry is None or entry["id"] in seen:
            continue
        seen.add(entry["id"])
        out.append(entry)
    return out[:MAX_ENTRIES]


def _modalities_have_image(value: Any) -> bool | None:
    if isinstance(value, list):
        lowered = [str(v).lower() for v in value]
        return "image" in lowered or "vision" in lowered
    return None


def _kind_from_words(*values: Any) -> str | None:
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, str) and item.strip().lower() in _EMBEDDING_WORDS:
                return "embedding"
    return None


# ---------------------------------------------------------------- llama.cpp router command lines (never forwarded)
_ARG_CTX = ("-c", "--ctx-size")


def _config_info(args: Any, preset: Any) -> tuple[int | None, bool | None]:
    """Extract (configured context, has vision projector) from a router status; raw text is discarded."""
    ctx: int | None = None
    vision: bool | None = None
    if isinstance(args, list):
        tokens = [t for t in args if isinstance(t, str)]
        for index, token in enumerate(tokens):
            if token in _ARG_CTX and index + 1 < len(tokens):
                ctx = ctx or _int(_to_int(tokens[index + 1]))
            elif token.startswith("--ctx-size="):
                ctx = ctx or _int(_to_int(token.split("=", 1)[1]))
            elif token in ("--mmproj", "-mm", "--mmproj-url") or token.startswith("--mmproj="):
                vision = True
    if isinstance(preset, str) and len(preset) <= 20_000:
        match = re.search(r"(?im)^\s*(?:ctx-size|c)\s*=\s*(\d+)\s*$", preset)
        if match:
            ctx = ctx or _int(int(match.group(1)))
        if re.search(r"(?im)^\s*mmproj(?:-url)?\s*=", preset):
            vision = True
    return ctx, vision


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


# ---------------------------------------------------------------- OpenAI-shaped lists (/v1/models, /models)
def detect_kind(rows: list, payload: Any = None) -> str:
    dicts = [r for r in rows if isinstance(r, dict)]
    owners = {str(r.get("owned_by", "")).lower() for r in dicts}
    if any(isinstance(r.get("status"), dict) and "value" in r["status"] and isinstance(r.get("aliases"), list) for r in dicts):
        return "llama_cpp_router"
    if "llamacpp" in owners:
        return "llama_cpp"
    if "llama-swap" in owners or any(isinstance(r.get("meta"), dict) and "llamaswap" in r["meta"] for r in dicts):
        return "llama_swap"
    if any(isinstance(r.get("loaded"), bool) for r in dicts):
        return "unsloth"
    if "strata-router" in owners or any("supports_vision" in r and "context_length" in r for r in dicts):
        return "strata_router"
    if "koboldcpp" in owners:
        return "koboldcpp"
    if "tabbyapi" in owners:
        return "tabbyapi"
    return "openai_compatible"


def _router_row(row: dict) -> dict | None:
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    configured, vision = _config_info(status.get("args"), status.get("preset"))
    if vision is None:
        vision = _modalities_have_image((row.get("architecture") or {}).get("input_modalities")) if isinstance(row.get("architecture"), dict) else None
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    return make_entry(row.get("id"), aliases=row.get("aliases"), state=_state(status.get("value")), failed=bool(status.get("failed")),
                      configured=configured, max_context=row.get("context_length") or meta.get("n_ctx_train"), vision=vision,
                      kind=_kind_from_words(row.get("tags")))


def _single_row(row: dict) -> dict | None:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    arch = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
    return make_entry(row.get("id"), max_context=meta.get("n_ctx_train") or row.get("context_length"),
                      vision=_modalities_have_image(arch.get("input_modalities")))


def _swap_row(row: dict) -> dict | None:
    meta = (row.get("meta") or {}).get("llamaswap") if isinstance(row.get("meta"), dict) else None
    meta = meta if isinstance(meta, dict) else {}
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    caps = row.get("capabilities")
    vision = ("vision" in [str(c).lower() for c in caps]) if isinstance(caps, list) else _bool(caps.get("vision")) if isinstance(caps, dict) else None
    aliases = (meta.get("aliases") if isinstance(meta.get("aliases"), list) else []) + (row.get("aliases") if isinstance(row.get("aliases"), list) else [])
    return make_entry(row.get("id"), label=row.get("name"), aliases=aliases, state=_state(status.get("value")),
                      configured=row.get("context_length"), vision=vision, kind=_kind_from_words(meta.get("type")))


def _unsloth_row(row: dict) -> dict | None:
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    state = _state(status.get("value"))
    if state == "unknown" and isinstance(row.get("loaded"), bool):
        state = "loaded" if row["loaded"] else "unloaded"
    return make_entry(row.get("id"), state=state, configured=row.get("context_length"), max_context=row.get("max_context_length"),
                      quant=row.get("quant"), kind=_kind_from_words(row.get("task")))


def _strata_row(row: dict) -> dict | None:
    return make_entry(row.get("id"), configured=row.get("context_length"), vision=_bool(row.get("supports_vision")))


def _generic_row(row: dict) -> dict | None:
    arch = row.get("architecture") if isinstance(row.get("architecture"), dict) else {}
    return make_entry(row.get("id"), max_context=row.get("max_model_len") or row.get("context_length"),
                      vision=_bool(row.get("supports_vision")) if "supports_vision" in row else _modalities_have_image(arch.get("input_modalities")))


_ROW_PARSERS = {
    "llama_cpp_router": _router_row, "llama_cpp": _single_row, "llama_swap": _swap_row,
    "unsloth": _unsloth_row, "strata_router": _strata_row,
}


def parse_openai_models(payload: Any) -> tuple[str, list[dict]]:
    """Parse an OpenAI-style list; the server family is detected from fingerprint fields."""
    rows = _rows(payload)
    kind = detect_kind(rows, payload)
    parser = _ROW_PARSERS.get(kind, _generic_row)
    entries = []
    for row in rows[: MAX_ENTRIES * 2]:
        if isinstance(row, dict):
            entries.append(parser(row))
        elif isinstance(row, str):
            entries.append(make_entry(row))
    return kind, _dedupe(entries)


# ---------------------------------------------------------------- LM Studio
def parse_lmstudio_v1(payload: Any) -> tuple[str, list[dict]]:
    """GET /api/v1/models (LM Studio 0.4+)."""
    entries = []
    for row in _rows(payload):
        if not isinstance(row, dict):
            continue
        loaded = row.get("loaded_instances") if isinstance(row.get("loaded_instances"), list) else []
        served = None
        for instance in loaded:
            if isinstance(instance, dict):
                served = (instance.get("config") or {}).get("context_length") if isinstance(instance.get("config"), dict) else None
                break
        caps = row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {}
        quant = row.get("quantization")
        kind_raw = str(row.get("type", "")).lower()
        entries.append(make_entry(row.get("key") or row.get("id"), label=row.get("display_name"), state="loaded" if loaded else "unloaded",
                                  served=served, max_context=row.get("max_context_length"), vision=_bool(caps.get("vision")),
                                  kind="embedding" if kind_raw in _EMBEDDING_WORDS else ("chat" if kind_raw == "llm" else None),
                                  quant=quant.get("name") if isinstance(quant, dict) else quant))
    return "lm_studio", _dedupe(entries)


def parse_lmstudio_v0(payload: Any) -> tuple[str, list[dict]]:
    """GET /api/v0/models (LM Studio 0.3.x REST API)."""
    entries = []
    for row in _rows(payload):
        if not isinstance(row, dict):
            continue
        kind_raw = str(row.get("type", "")).lower()
        entries.append(make_entry(row.get("id"), state=_state(row.get("state")), served=row.get("loaded_context_length"),
                                  max_context=row.get("max_context_length"), vision=True if kind_raw == "vlm" else (False if kind_raw == "llm" else None),
                                  kind="embedding" if kind_raw in _EMBEDDING_WORDS else ("chat" if kind_raw in ("llm", "vlm") else None),
                                  quant=row.get("quantization")))
    return "lm_studio", _dedupe(entries)


# ---------------------------------------------------------------- Ollama
def parse_ollama_tags(payload: Any) -> tuple[str, list[dict]]:
    """GET /api/tags. State stays 'unknown' until merge_ollama_ps() runs."""
    entries = []
    for row in _rows(payload):
        if not isinstance(row, dict):
            continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        family = str(details.get("family", "")).lower()
        entries.append(make_entry(row.get("name") or row.get("model"), quant=details.get("quantization_level"),
                                  kind="embedding" if "bert" in family else None))
    return "ollama", _dedupe(entries)


def merge_ollama_ps(entries: list[dict], payload: Any) -> list[dict]:
    """GET /api/ps: models in memory are loaded (with their served context); the rest are unloaded."""
    running: dict[str, int | None] = {}
    for row in _rows(payload):
        if isinstance(row, dict):
            name = _text(row.get("name") or row.get("model"))
            if name:
                running[name] = _int(row.get("context_length"))
    merged = []
    for entry in entries:
        copy = {**entry, "context": dict(entry["context"])}
        if copy["id"] in running:
            copy["state"] = "loaded"
            copy["context"]["served"] = running[copy["id"]] or copy["context"]["served"]
        else:
            copy["state"] = "unloaded"
        merged.append(copy)
    return merged


# ---------------------------------------------------------------- single-model / router enrichment
def merge_llamacpp_props(entries: list[dict], payload: Any) -> list[dict]:
    """GET /props of a single-model llama-server: served context, vision and sleeping state."""
    if len(entries) != 1 or not isinstance(payload, dict) or payload.get("role") == "router":
        return entries
    settings = payload.get("default_generation_settings") if isinstance(payload.get("default_generation_settings"), dict) else {}
    modalities = payload.get("modalities") if isinstance(payload.get("modalities"), dict) else {}
    copy = {**entries[0], "context": dict(entries[0]["context"])}
    copy["context"]["served"] = _int(settings.get("n_ctx")) or copy["context"]["served"]
    if _bool(modalities.get("vision")) is not None:
        copy["vision"] = modalities["vision"]
    copy["state"] = "sleeping" if payload.get("is_sleeping") is True else "loaded"
    return [copy]


def merge_strata_status(entries: list[dict], payload: Any) -> list[dict]:
    """GET /status of the Strata router: which configuration is loaded and what context clients get."""
    by_id: dict[str, dict] = {}
    for row in _rows(payload):
        if isinstance(row, dict) and _text(row.get("id")):
            by_id[row["id"]] = row
    merged = []
    for entry in entries:
        copy = {**entry, "context": dict(entry["context"])}
        row = by_id.get(copy["id"])
        if row:
            if isinstance(row.get("loaded"), bool):
                copy["state"] = "loaded" if row["loaded"] else "unloaded"
            copy["context"]["served"] = _int(row.get("client_context")) or _int(row.get("context")) or copy["context"]["served"]
            if _bool(row.get("vision")) is not None:
                copy["vision"] = row["vision"]
        merged.append(copy)
    return merged


def entries_for(entries: list[dict], model_type: str) -> list[dict]:
    """Filter by the endpoint-provided kind only: unknown kinds are kept in both lists."""
    wanted = "embedding" if model_type == "embedding" else "chat"
    return [e for e in entries if e["kind"] in (None, wanted)]
