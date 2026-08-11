#!/bin/bash
# AI-Link Bridge Server Startup Script
# Usage: ./start_bridge.sh [port] [host]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=${1:-8765}
HOST=${2:-0.0.0.0}

export AI_LINK_PORT="$PORT"
export AI_LINK_HOST="$HOST"

echo "============================================"
echo "  AI-Link Bridge Server"
echo "  Protocol: ailink.v1"
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "============================================"
echo ""
echo "Endpoints:"
echo "  GET  /health         - Server health check"
echo "  GET  /capabilities   - Protocol capabilities"
echo "  GET  /sessions       - Active client sessions"
echo "  GET  /metrics        - Session metrics"
echo "  POST /task           - Validate a task scaffold (no dispatch)"
echo "  WS   /ws             - Client stream/control channel"
echo ""

echo "Starting bridge server..."
python3 bridge_server.py
