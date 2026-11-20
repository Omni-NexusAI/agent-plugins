"""Small statistics helpers (standard library only)."""

from __future__ import annotations

import math
import random


def bootstrap_ci(outcomes: list[bool], samples: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap interval for an accuracy."""
    if not outcomes:
        return 0.0, 0.0
    rng = random.Random(seed)
    count = len(outcomes)
    means = sorted(sum(outcomes[rng.randrange(count)] for _ in range(count)) / count
                   for _ in range(samples))
    return means[int(0.025 * samples)], means[min(samples - 1, int(0.975 * samples))]


def mcnemar_exact(fixed: int, broke: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs."""
    total = fixed + broke
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, index) for index in range(min(fixed, broke) + 1)) / 2 ** total
    return min(1.0, 2 * tail)


def paired(baseline: list[bool], arm: list[bool]) -> dict[str, float]:
    fixed = sum(1 for before, after in zip(baseline, arm) if after and not before)
    broke = sum(1 for before, after in zip(baseline, arm) if before and not after)
    return {"fixed": fixed, "broke": broke, "p": mcnemar_exact(fixed, broke)}
