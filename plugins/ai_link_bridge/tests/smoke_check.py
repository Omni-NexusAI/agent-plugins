from pathlib import Path

REQUIRED = [
    "plugin.yaml",
    "default_config.yaml",
    "README.md",
    "helpers/protocol.py",
    "helpers/session_state.py",
    "tools/ai_link_bridge_status.py",
    "tools/ai_link_bridge_task.py",
    "docs/protocol.md",
]


def main() -> int:
    base = Path(__file__).resolve().parents[1]
    missing = [rel for rel in REQUIRED if not (base / rel).exists()]
    if missing:
        print({"ok": False, "missing": missing})
        return 1
    print({"ok": True, "files": REQUIRED})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
