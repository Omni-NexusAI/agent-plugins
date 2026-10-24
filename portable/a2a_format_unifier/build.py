"""Assemble the Agent Zero adapter without dependencies on the monorepo at runtime."""
import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def sources():
    result = {}
    adapter = ROOT / "adapters" / "agent_zero"
    for source in adapter.rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts:
            result[source.relative_to(adapter)] = source
    for source in (ROOT / "core").glob("*.py"):
        result[Path("helpers") / source.name] = source
    result[Path("LICENSE")] = REPO / "LICENSE"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO / "plugins" / "a2a_format_unifier")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = sources()
    if args.check:
        actual = {p.relative_to(args.output) for p in args.output.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts}
        wrong = [str(p) for p, src in expected.items()
                 if not (args.output / p).is_file() or (args.output / p).read_bytes() != src.read_bytes()]
        extra = actual - set(expected)
        if wrong or extra:
            raise SystemExit("Assembly differs: " + repr({"changed_or_missing": wrong, "extra": sorted(map(str, extra))}))
        print("Assembly matches portable source")
        return
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("Output must be empty; assembly never deletes existing files")
    for relative, source in expected.items():
        target = args.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    print(f"Assembled {len(expected)} files")


if __name__ == "__main__":
    main()
