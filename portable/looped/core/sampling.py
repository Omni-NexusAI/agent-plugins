"""Sampling settings for extra candidates.

Variant 0 is the host's own call and gets no overrides. Later variants get a
distinct seed and, when configured, a temperature high enough that a greedy
host setting does not simply reproduce the first candidate.
"""

from __future__ import annotations

from typing import Any


def variant_params(cfg: dict[str, Any], variant: int) -> dict[str, Any]:
    if variant <= 0:
        return {}
    sampling = cfg["sampling"]
    params: dict[str, Any] = {"seed": int(sampling["seed_base"]) + int(variant)}
    if sampling.get("temperature") is not None:
        params["temperature"] = float(sampling["temperature"])
    return params
