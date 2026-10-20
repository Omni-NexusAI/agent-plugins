"""Download the pinned upstream Agent Zero files used by the tests.

Usage (from the plugin directory):  python tests/fixtures/fetch_fixtures.py

Files are saved byte-exact under tests/fixtures/a0-<version>/ with a
MANIFEST.json (source sha + sha256). Agent Zero is MIT licensed
(Copyright (c) 2025 Agent Zero, s.r.o); see tests/fixtures/LICENSE-agent-zero.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "compat"))

import upstream  # noqa: E402


def main() -> int:
    for name, sha in upstream.PINNED.items():
        target = HERE / f"a0-{name}"
        manifest = {"version": name, "source": f"https://github.com/{upstream.REPO}", "commit": sha, "files": {}}
        for path in upstream.WATCHED:
            data = upstream.fetch(sha, path)
            out = target / path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            manifest["files"][path] = {"sha256": upstream.sha256(data), "bytes": len(data)}
            print(f"{name}  {path}  {len(data)} bytes")
        (target / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    license_text = upstream.fetch(upstream.PINNED["v2.14"], "LICENSE")
    (HERE / "LICENSE-agent-zero").write_bytes(license_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
