#!/usr/bin/env bash
# Preview or propose a standalone plugin repository sync.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT_DIR/sync-to-repos.py" "$@"
fi
exec python "$SCRIPT_DIR/sync-to-repos.py" "$@"
