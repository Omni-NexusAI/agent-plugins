"""Looped mode core: framework-independent test-time-compute strategies.

Nothing in this package imports a host framework. A host adapter supplies
callables that reach its model; the benchmark supplies its own.
"""

from .canonical import FINAL_TOOLS, build_candidate, canonical_key, parse_step, salvage_step
from .config import DEFAULTS, MODES, merge_config
from .controller import TurnState, checkpoint, is_active
from .metrics import Metrics
from .pipeline import StepContext, resolve_step
from .types import Candidate, Decision

__version__ = "0.1.0"

__all__ = [
    "Candidate", "DEFAULTS", "Decision", "FINAL_TOOLS", "MODES", "Metrics",
    "StepContext", "TurnState", "build_candidate", "canonical_key",
    "checkpoint", "is_active", "merge_config", "parse_step", "resolve_step",
    "salvage_step",
]
