"""Assemble/check the independent Agent Zero package from portable sources."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ADAPTER = HERE / "adapters" / "agent_zero"
CORE = HERE / "core"
DEST = ROOT / "plugins" / "system_1"


def files() -> dict[Path, Path]:
    plan = {path: DEST / path.relative_to(ADAPTER) for path in ADAPTER.rglob("*")
            if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts}
    plan.update({path: DEST / "helpers" / "system_1_core" / path.relative_to(CORE)
                 for path in CORE.rglob("*")
                 if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts})
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    plan = files()
    expected = {target.relative_to(DEST) for target in plan.values()}
    existing = {path.relative_to(DEST) for path in DEST.rglob("*") if path.is_file()} if DEST.exists() else set()
    if args.check:
        mismatches = [str(target) for source, target in plan.items()
                      if not target.is_file() or source.read_bytes() != target.read_bytes()]
        extras = existing - expected
        if mismatches or extras:
            print(f"Assembly differs: changed={mismatches}, extra={sorted(map(str, extras))}")
            return 1
        print(f"Assembly current: {len(plan)} files")
        return 0
    if existing - expected:
        parser.error("Existing assembled package has extra files; review them before rebuilding")
    for source, target in plan.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f"Assembled {len(plan)} files to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
