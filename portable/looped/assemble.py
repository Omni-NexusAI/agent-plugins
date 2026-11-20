"""Assemble or check the independent Agent Zero package from portable sources.

    python portable/looped/assemble.py           # write plugins/looped
    python portable/looped/assemble.py --check   # verify it is current
    python portable/looped/assemble.py --dest D  # write a copy elsewhere

The assembled package contains the adapter plus a copy of ``core`` at
``helpers/looped_core`` and runs without this source tree.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ADAPTER = HERE / "adapters" / "agent_zero"
CORE = HERE / "core"
DEST = ROOT / "plugins" / "looped"


def _sources(base: Path):
    return (path for path in sorted(base.rglob("*"))
            if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts)


def files(dest: Path) -> dict[Path, Path]:
    plan = {path: dest / path.relative_to(ADAPTER) for path in _sources(ADAPTER)}
    plan.update({path: dest / "helpers" / "looped_core" / path.relative_to(CORE)
                 for path in _sources(CORE)})
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dest", type=Path, default=DEST)
    args = parser.parse_args()
    dest = args.dest.resolve()
    plan = files(dest)
    expected = {target.relative_to(dest) for target in plan.values()}
    existing = ({path.relative_to(dest) for path in _sources(dest)}
                if dest.exists() else set())
    if args.check:
        changed = [str(target.relative_to(dest)) for source, target in plan.items()
                   if not target.is_file() or source.read_bytes() != target.read_bytes()]
        extra = sorted(str(path) for path in existing - expected)
        if changed or extra:
            print(f"Assembly differs: changed={changed}, extra={extra}")
            return 1
        print(f"Assembly current: {len(plan)} files")
        return 0
    if existing - expected:
        parser.error("Assembled package has files the sources do not: "
                     f"{sorted(str(path) for path in existing - expected)}")
    for source, target in plan.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f"Assembled {len(plan)} files to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
