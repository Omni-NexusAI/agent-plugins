"""Validate specialist and media-embedding configuration while keeping unknown host keys intact."""

MODALITIES = ("image", "audio", "video")
BOUNDS = {"max_media_mb": (1, 200), "timeout_seconds": (5, 600), "recall_limit": (1, 20), "recall_threshold": (0, 1),
          "recall_media_threshold": (0, 1)}
EMBEDDING_DEFAULTS = {"max_media_mb": 20, "timeout_seconds": 60, "recall_attachments": True, "recall_limit": 3,
                      "recall_threshold": 0.84, "recall_media_threshold": 0.95, "index_knowledge_media": True}


def get_plugin_config(default=None, **kwargs):
    """Fill media-embedding defaults into configs saved before the section existed."""
    if isinstance(default, dict):
        section = default.get("embedding") if isinstance(default.get("embedding"), dict) else {}
        default["embedding"] = {**EMBEDDING_DEFAULTS, **section,
                                "models": section.get("models") if isinstance(section.get("models"), dict) else {}}
    return default


def save_plugin_config(result=None, settings=None, **kwargs):
    if not isinstance(settings, dict):
        return settings
    for role in ("tool", "coding"):
        section = settings.get(role, {})
        if not isinstance(section, dict):
            raise ValueError(f"{role} model settings must be an object")
        if section.get("enabled") and (
            not isinstance(section.get("provider"), str) or not section["provider"].strip()
            or not isinstance(section.get("name"), str) or not section["name"].strip()
        ):
            raise ValueError(f"{role} specialist requires provider and model name")
    embedding = settings.get("embedding", {})
    if not isinstance(embedding, dict):
        raise ValueError("embedding settings must be an object")
    models = embedding.get("models", {})
    if not isinstance(models, dict):
        raise ValueError("embedding models must be an object keyed by provider/model")
    for key, entry in models.items():
        if not isinstance(key, str) or "/" not in key or not isinstance(entry, dict):
            raise ValueError("each embedding model entry needs a provider/model key and an object")
        if any(kind in entry and not isinstance(entry[kind], bool) for kind in MODALITIES):
            raise ValueError("embedding modalities must be true or false")
    for name, (low, high) in BOUNDS.items():
        value = embedding.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high):
            raise ValueError(f"embedding {name} must be between {low} and {high}")
    for name in ("recall_attachments", "index_knowledge_media"):
        if name in embedding and not isinstance(embedding[name], bool):
            raise ValueError(f"embedding {name} must be true or false")
    return settings
