"""Store and find media in Agent Zero memory with the multimodal Embedding model.

Media memories are ordinary memory documents whose vector comes from the media
itself, so text queries, ``memory_load`` and recall find them alongside text.
The document text is the description plus the file reference. Agent Zero
re-embeds documents from their text when it rebuilds an index; ``repair``
detects that through a stored vector fingerprint and re-embeds from the file.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from usr.plugins.auxiliary_model_roles.helpers import media_embedding as me


KNOWLEDGE_STATE = "media_knowledge.json"
_repaired: dict[str, tuple[str, int]] = {}
_indexed: set[tuple[str, str]] = set()


def _memory():
    from plugins._memory.helpers import memory
    return memory


def fingerprint(vector) -> str:
    return ",".join(f"{float(x):.3f}" for x in list(vector)[:12])


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_model(db) -> str:
    """The provider/name the memory index was built with, from Agent Zero's own marker file."""
    path = os.path.join(_memory().abs_db_dir(db.memory_subdir), "embedding.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            marker = json.load(handle)
        return me.model_key(marker.get("model_provider", ""), marker.get("model_name", ""))
    except (OSError, ValueError, AttributeError):
        return ""


def check_space(db, target: me.Target, vector: list[float]):
    built = index_model(db)
    if built and built != target.key:
        raise me.MediaEmbeddingError(f"Memory was built with {built}, not the active Embedding model {target.key}")
    dims = getattr(db.db.index, "d", len(vector))
    if dims != len(vector):
        raise me.MediaEmbeddingError(f"Media vectors have {len(vector)} dimensions but memory uses {dims}")


def content_for(kind: str, path: str, description: str) -> str:
    text = description.strip() or f"{kind.title()} {os.path.basename(path)}"
    return f"{text}\n[{kind} file: {path}]"


def _add(db, doc_id: str, content: str, vector: list[float], metadata: dict):
    db.db.add_embeddings([(content, vector)], metadatas=[metadata], ids=[doc_id])


async def save(agent, path: str, description: str = "", area: str = "", extra: dict | None = None) -> str:
    memory = _memory()
    db = await memory.Memory.get(agent)
    target = me.current(agent)
    kind, vector = await me.embed_file(agent, path, target)
    check_space(db, target, vector)
    doc_id = db._generate_doc_id()
    metadata = {"id": doc_id, "timestamp": memory.Memory.get_timestamp(),
                "area": area or memory.Memory.Area.MAIN.value, **(extra or {}),
                "media_type": kind, "media_path": path, "media_sha256": sha256(_absolute(path)),
                "media_model": target.key, "media_fp": fingerprint(vector)}
    _add(db, doc_id, content_for(kind, path, description), vector, metadata)
    db._save_db()
    return doc_id


async def search(agent, path: str, limit: int = 5, threshold: float | None = None, filter: str = "",
                 media_threshold: float | None = None) -> list[tuple[Any, float]]:
    """Memories similar to a media file. Media-to-media scores run higher than media-to-text, so
    other media memories use their own threshold (defaults from plugin settings)."""
    memory = _memory()
    options = me.settings(agent)
    text_level = float(options["recall_threshold"] if threshold is None else threshold)
    media_level = float(media_threshold if media_threshold is not None
                        else options["recall_media_threshold"] if threshold is None else threshold)
    db = await memory.Memory.get(agent)
    target = me.current(agent)
    _kind, vector = await me.embed_file(agent, path, target)
    check_space(db, target, vector)
    comparator = memory.Memory._get_comparator(filter) if filter else None
    found = await db.db.asimilarity_search_with_score_by_vector(vector, k=max(1, int(limit)), filter=comparator)
    scored = [(doc, memory.Memory._cosine_normalizer(score)) for doc, score in found]
    return [(doc, score) for doc, score in scored
            if score >= (media_level if (doc.metadata or {}).get("media_type") else text_level)]


def _absolute(path: str) -> str:
    if os.path.isabs(path):
        return path
    from helpers import files
    return files.get_abs_path(path)


def _stored_vector(db, doc_id: str):
    for position, stored_id in db.db.index_to_docstore_id.items():
        if stored_id == doc_id:
            try:
                return db.db.index.reconstruct(int(position))
            except Exception:
                return None
    return None


async def repair(agent, limit: int = 25) -> int:
    """Re-embed media memories whose vector no longer comes from their file. Returns the count fixed."""
    memory = _memory()
    db = await memory.Memory.get(agent)
    try:
        target = me.current(agent)
    except me.MediaEmbeddingError:
        return 0
    if not any(target.modalities.values()) or (index_model(db) and index_model(db) != target.key):
        return 0
    marker = (target.key, int(getattr(db.db.index, "ntotal", 0)))
    if _repaired.get(db.memory_subdir) == marker:
        return 0
    fixed = 0
    for doc_id, doc in list(db.db.docstore._dict.items()):
        meta = doc.metadata or {}
        kind, path = meta.get("media_type"), meta.get("media_path")
        if not kind or not path or not target.modalities.get(kind):
            continue
        stored = _stored_vector(db, doc_id)
        if meta.get("media_model") == target.key and stored is not None and fingerprint(stored) == meta.get("media_fp"):
            continue
        if fixed >= limit or not os.path.isfile(_absolute(path)):
            continue
        try:
            _kind, vector = await me.embed_file(agent, path, target)
        except me.MediaEmbeddingError:
            continue
        db.db.delete([doc_id])
        _add(db, doc_id, doc.page_content, vector,
             {**meta, "media_model": target.key, "media_fp": fingerprint(vector)})
        fixed += 1
    if fixed:
        db._save_db()
    _repaired[db.memory_subdir] = (target.key, int(getattr(db.db.index, "ntotal", 0)))
    return fixed


def _knowledge_files(agent, memory_subdir: str) -> dict[str, str]:
    """Media files in the agent's knowledge folders, mapped to their memory area."""
    memory = _memory()
    subdirs = memory.get_knowledge_subdirs_by_memory_subdir(memory_subdir, list(agent.config.knowledge_subdirs or []))
    found: dict[str, str] = {}
    for subdir in subdirs:
        root = memory.abs_knowledge_dir(subdir)
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                path = os.path.join(root, name)
                if os.path.isfile(path) and not name.startswith(".") and me.kind_of(path):
                    found[path] = memory.Memory.Area.MAIN.value
        for area in memory.Memory.Area:
            area_root = memory.abs_knowledge_dir(subdir, area.value)
            for folder, _dirs, names in os.walk(area_root):
                for name in sorted(names):
                    path = os.path.join(folder, name)
                    if not name.startswith(".") and me.kind_of(path):
                        found[path] = area.value
    return found


async def index_knowledge(agent, force: bool = False) -> dict[str, int]:
    """Bring media files in knowledge folders into memory; returns added/removed/failed counts."""
    memory = _memory()
    db = await memory.Memory.get(agent)
    counts = {"added": 0, "removed": 0, "failed": 0, "kept": 0}
    try:
        target = me.current(agent)
    except me.MediaEmbeddingError:
        return counts
    if not force and (db.memory_subdir, target.key) in _indexed:
        return counts
    if not any(target.modalities.values()) or (index_model(db) and index_model(db) != target.key):
        return counts
    state_path = os.path.join(memory.abs_db_dir(db.memory_subdir), KNOWLEDGE_STATE)
    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        state = {}
    files = _knowledge_files(agent, db.memory_subdir)
    present = db.db.docstore._dict
    for path, entry in list(state.items()):
        kind = me.kind_of(path)
        if path not in files or not target.modalities.get(kind) or entry.get("model") != target.key:
            if entry.get("id") in present:
                db.db.delete([entry["id"]])
                counts["removed"] += 1
            state.pop(path)
    for path, area in files.items():
        kind = me.kind_of(path)
        if not target.modalities.get(kind):
            continue
        try:
            checksum = sha256(path)
            entry = state.get(path) or {}
            if entry.get("checksum") == checksum and entry.get("id") in present:
                counts["kept"] += 1
                continue
            if entry.get("id") in present:
                db.db.delete([entry["id"]])
            _kind, vector = await me.embed_file(agent, path, target)
            check_space(db, target, vector)
            doc_id = db._generate_doc_id()
            metadata = {"id": doc_id, "timestamp": memory.Memory.get_timestamp(), "area": area,
                        "knowledge_source": True, "source_file": path, "media_type": kind, "media_path": path,
                        "media_sha256": checksum, "media_model": target.key, "media_fp": fingerprint(vector)}
            _add(db, doc_id, content_for(kind, path, ""), vector, metadata)
            state[path] = {"checksum": checksum, "id": doc_id, "model": target.key}
            counts["added"] += 1
        except (me.MediaEmbeddingError, OSError):
            counts["failed"] += 1
    if counts["added"] or counts["removed"]:
        db._save_db()
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    _indexed.add((db.memory_subdir, target.key))
    return counts
