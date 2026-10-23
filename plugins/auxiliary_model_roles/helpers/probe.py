"""Check which media an Embedding model server accepts, with tiny built-in samples.

Runs only when the user clicks Check server. It sends one short text, a 64x64
image, one second of tone and a one-second test video, and reports per
modality whether a vector came back and its dimensions.
"""

from __future__ import annotations

import io
import math
import os
import struct
import wave
import zlib

from usr.plugins.auxiliary_model_roles.helpers import media_embedding as me


ASSETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")


def sample_png(size: int = 64) -> bytes:
    rows = b"".join(b"\x00" + bytes(v for x in range(size) for v in (x * 4 % 256, y * 4 % 256, 128))
                    for y in range(size))
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def sample_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * n / rate)))
                      for n in range(int(seconds * rate)))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(frames)
    return buffer.getvalue()


def samples() -> dict[str, list[dict]]:
    with open(os.path.join(ASSETS, "probe.mp4"), "rb") as handle:
        video = handle.read()
    return {"text": [{"type": "text", "text": "A short test sentence."}],
            "image": [me.part("image", sample_png(), "probe.png")],
            "audio": [me.part("audio", sample_wav(), "probe.wav")],
            "video": [me.part("video", video, "probe.mp4")]}


async def check(cfg: dict, kinds=me.MODALITIES, timeout: float = 60) -> dict:
    target = me.resolve(cfg)
    results: dict[str, dict] = {}
    for kind, parts in samples().items():
        if kind != "text" and kind not in kinds:
            continue
        try:
            vector = (await me.embed_parts(target, [parts], timeout=timeout))[0]
            results[kind] = {"ok": True, "dims": len(vector)}
        except me.MediaEmbeddingError as error:
            results[kind] = {"ok": False, "error": str(error)}
    text_dims = results.get("text", {}).get("dims")
    for kind in me.MODALITIES:
        result = results.get(kind)
        if result and result.get("ok") and text_dims and result["dims"] != text_dims:
            result.update(ok=False, error=f"{result['dims']} dimensions; text uses {text_dims}")
    return {"ok": bool(results.get("text", {}).get("ok")), "model": target.key, "results": results}
