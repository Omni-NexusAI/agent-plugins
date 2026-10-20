"""Load plugin helper/api modules by path, the way the Agent Zero loader does (no package context)."""
from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
VECTORS = PLUGIN_DIR / "tests" / "vectors"
_counter = itertools.count()


def load_module(relative_path: str, *, alias: str | None = None):
    """Return a fresh module object for plugin file `relative_path` (each call is a new copy)."""
    path = PLUGIN_DIR / relative_path
    name = alias or f"_pp_test_{path.stem}_{next(_counter)}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_helper(name: str):
    return load_module(f"helpers/{name}.py")
