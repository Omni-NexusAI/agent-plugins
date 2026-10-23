"""Embed images, audio and video with the active Embedding model when it accepts them.

Text embeddings stay on Agent Zero's native path. Media goes to the same model's
OpenAI-compatible ``/embeddings`` route as one ``content`` array per item, the
shape llama.cpp ``llama-server`` (with ``--mmproj``) and OpenRouter accept.
Capabilities are declared per model by the user and confirmed by Check server;
nothing here falls back to another model or converts media to text.
"""

from __future__ import annotations

import base64
import math
import mimetypes
import os
from dataclasses import dataclass, field
from typing import Any

from helpers import plugins


PLUGIN = "auxiliary_model_roles"
MODALITIES = ("image", "audio", "video")
EXTENSIONS = {
    "image": {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".gif": "image/gif", ".bmp": "image/bmp"},
    "audio": {".wav": "wav", ".mp3": "mp3", ".flac": "flac"},
    "video": {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
              ".avi": "video/x-msvideo"},
}
# Agent Zero providers whose LiteLLM route is the OpenAI wire format.
COMPATIBLE = {"openai", "hosted_vllm", "lm_studio"}
DEFAULTS = {"max_media_mb": 20, "timeout_seconds": 60, "recall_attachments": True, "recall_limit": 3,
            "recall_threshold": 0.84, "recall_media_threshold": 0.95, "index_knowledge_media": True}


class MediaEmbeddingError(RuntimeError):
    """A media embedding request that cannot be served as configured."""


@dataclass
class Target:
    provider: str
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    modalities: dict[str, bool] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return model_key(self.provider, self.name)


def model_key(provider: str, name: str) -> str:
    return f"{str(provider or '').strip().lower()}/{str(name or '').strip()}"


def settings(agent=None) -> dict:
    config = plugins.get_plugin_config(PLUGIN, agent) or {}
    section = config.get("embedding") if isinstance(config.get("embedding"), dict) else {}
    merged = {**DEFAULTS, **{k: v for k, v in section.items() if k in DEFAULTS}}
    merged["models"] = section.get("models") if isinstance(section.get("models"), dict) else {}
    return merged


def declared(agent, provider: str, name: str) -> dict[str, bool]:
    entry = settings(agent)["models"].get(model_key(provider, name))
    entry = entry if isinstance(entry, dict) else {}
    return {kind: entry.get(kind) is True for kind in MODALITIES}


def kind_of(path: str) -> str:
    ext = os.path.splitext(str(path or ""))[1].lower()
    for kind, table in EXTENSIONS.items():
        if ext in table:
            return kind
    return ""


def resolve(cfg: dict, agent=None) -> Target:
    """Resolve an Embedding model section to an OpenAI-compatible endpoint and its headers."""
    from helpers.providers import get_provider_config
    import models

    provider = str(cfg.get("provider") or "").strip().lower()
    name = str(cfg.get("name") or "").strip()
    if not provider or not name:
        raise MediaEmbeddingError("The Embedding model has no provider or model name")
    provider_cfg = get_provider_config("embedding", provider) or {}
    litellm_provider = str(provider_cfg.get("litellm_provider") or provider).lower()
    if provider == "other":
        litellm_provider = "openai"
    if litellm_provider not in COMPATIBLE:
        raise MediaEmbeddingError(f"Provider '{provider}' has no OpenAI-compatible embeddings route for media")
    kwargs = dict(provider_cfg.get("kwargs") or {}) if isinstance(provider_cfg.get("kwargs"), dict) else {}
    kwargs.update(cfg.get("kwargs") if isinstance(cfg.get("kwargs"), dict) else {})
    base = str(cfg.get("api_base") or kwargs.get("api_base") or "").strip()
    if not base and provider == "openai":
        base = "https://api.openai.com/v1"
    if not base:
        raise MediaEmbeddingError("Set an API base URL for this Embedding model")
    key = str(cfg.get("api_key") or kwargs.get("api_key") or models.get_api_key(provider) or "")
    headers = {"Content-Type": "application/json"}
    if key and key not in ("None", "NA"):
        headers["Authorization"] = f"Bearer {key}"
    extra = kwargs.get("extra_headers")
    if isinstance(extra, dict):
        headers.update({str(k): str(v) for k, v in extra.items()})
    return Target(provider, name, base.rstrip("/") + "/embeddings", headers, declared(agent, provider, name))


def current(agent) -> Target:
    from plugins._model_config.helpers.model_config import get_embedding_model_config
    return resolve(get_embedding_model_config(agent), agent)


def read_media(path: str, agent=None, limit_mb: float | None = None) -> tuple[str, bytes]:
    kind = kind_of(path)
    if not kind:
        raise MediaEmbeddingError("Unsupported media type; use an image, wav/mp3/flac audio or a video file")
    from helpers import files
    absolute = path if os.path.isabs(path) else files.get_abs_path(path)
    if not os.path.isfile(absolute):
        raise MediaEmbeddingError(f"Media file not found: {path}")
    limit = float(limit_mb if limit_mb is not None else settings(agent)["max_media_mb"])
    if os.path.getsize(absolute) > limit * 1024 * 1024:
        raise MediaEmbeddingError(f"Media file is larger than {limit:g} MB")
    with open(absolute, "rb") as handle:
        return kind, handle.read()


def part(kind: str, data: bytes, path: str = "") -> dict:
    ext = os.path.splitext(path)[1].lower()
    encoded = base64.b64encode(data).decode("ascii")
    if kind == "image":
        mime = EXTENSIONS["image"].get(ext) or mimetypes.guess_type(path)[0] or "image/png"
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
    if kind == "audio":
        return {"type": "input_audio", "input_audio": {"data": encoded, "format": EXTENSIONS["audio"].get(ext, "wav")}}
    if kind == "video":
        mime = EXTENSIONS["video"].get(ext, "video/mp4")
        return {"type": "input_video", "input_video": {"url": f"data:{mime};base64,{encoded}"}}
    raise MediaEmbeddingError(f"Unknown media kind '{kind}'")


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(x) * float(x) for x in vector))
    return [float(x) / norm for x in vector] if norm > 0 else [float(x) for x in vector]


async def embed_parts(target: Target, items: list[list[dict]], timeout: float = 60) -> list[list[float]]:
    """Return one normalized vector per item; each item is a list of content parts."""
    import httpx

    body: dict[str, Any] = {"model": target.name, "encoding_format": "float",
                            "input": [{"content": parts} for parts in items]}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(target.url, json=body, headers=target.headers)
    except httpx.HTTPError as error:
        raise MediaEmbeddingError(f"Embedding server unreachable ({type(error).__name__})") from error
    if response.status_code >= 400:
        detail = ""
        try:
            payload = response.json()
            detail = str((payload.get("error") or {}).get("message") or payload.get("error") or "")
        except ValueError:
            detail = response.text
        raise MediaEmbeddingError(f"Embedding server refused the media (HTTP {response.status_code}): {detail[:300]}")
    try:
        data = sorted(response.json()["data"], key=lambda row: row.get("index", 0))
        vectors = [normalize(row["embedding"]) for row in data]
    except (ValueError, KeyError, TypeError) as error:
        raise MediaEmbeddingError("Embedding server returned an unexpected response") from error
    if len(vectors) != len(items) or any(not vector for vector in vectors):
        raise MediaEmbeddingError("Embedding server returned the wrong number of vectors")
    return vectors


async def embed_file(agent, path: str, target: Target | None = None, text: str = "") -> tuple[str, list[float]]:
    """Embed one media file (optionally with accompanying text) with the active Embedding model."""
    target = target or current(agent)
    kind, data = read_media(path, agent)
    if not target.modalities.get(kind):
        raise MediaEmbeddingError(f"The Embedding model {target.key} is not set to accept {kind} input")
    parts = [part(kind, data, path)]
    if text.strip():
        parts.append({"type": "text", "text": text.strip()})
    vectors = await embed_parts(target, [parts], timeout=float(settings(agent)["timeout_seconds"]))
    return kind, vectors[0]
