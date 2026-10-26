#!/bin/bash
# Start the full JaegerAI stack for testing
# Usage: ./scripts/start-test-env.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Configuration
export JAEGER_TEST_MODE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/test-pycache"
export JAEGER_STATE_DIR="${JAEGER_STATE_DIR:-/tmp/jaeger-test-state}"
export JAEGER_VENV="${JAEGER_VENV:-$HOME/.jaeger/venv}"

# Clean up previous test state
if [ -d "$JAEGER_STATE_DIR" ]; then
    echo "→ Cleaning previous test state..."
    rm -rf "$JAEGER_STATE_DIR"
fi
mkdir -p "$JAEGER_STATE_DIR"

# Find Python
if [ -x "$JAEGER_VENV/bin/python" ]; then
    PY="$JAEGER_VENV/bin/python"
else
    PY="python3"
fi

echo "========================================"
echo "  Starting JaegerAI Test Environment"
echo "========================================"
echo ""
echo "  Python:     $PY"
echo "  State dir:  $JAEGER_STATE_DIR"
echo "  Gateway:    http://127.0.0.1:33418"
echo "  WebUI:      http://127.0.0.1:8790"
echo "  WebSocket:  ws://127.0.0.1:33418/ws"
echo ""

# Start Gateway in background
echo "→ Starting Gateway..."
"$PY" -m jaeger_ai gateway daemon > /tmp/jaeger-gateway.log 2>&1 &
GATEWAY_PID=$!
echo "  Gateway PID: $GATEWAY_PID"

# Wait for Gateway to be ready
GATEWAY_URL="http://127.0.0.1:33418"
echo "→ Waiting for Gateway..."
for i in $(seq 1 30); do
    if curl -s "$GATEWAY_URL/health" > /dev/null 2>&1; then
        echo "  ✓ Gateway is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "  ✗ Gateway failed to start"
        cat /tmp/jaeger-gateway.log
        kill $GATEWAY_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Build WebUI if needed
WEBUI_DIST="$REPO_ROOT/jaeger_ai/interfaces/ui/dist"
if [ ! -d "$WEBUI_DIST" ]; then
    echo "→ Building WebUI..."
    cd "$REPO_ROOT/jaeger_ai/interfaces/ui"
    npm install --silent 2>/dev/null || true
    npm run build --silent 2>/dev/null || true
    cd "$REPO_ROOT"
fi

# Start WebUI in background
echo "→ Starting WebUI..."
"$PY" -m jaeger_ai.features.webui.server > /tmp/jaeger-webui.log 2>&1 &
WEBUI_PID=$!
echo "  WebUI PID: $WEBUI_PID"

# Wait for WebUI to be ready
WEBUI_URL="http://127.0.0.1:8790"
echo "→ Waiting for WebUI..."
for i in $(seq 1 30); do
    if curl -s "$WEBUI_URL" > /dev/null 2>&1; then
        echo "  ✓ WebUI is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "  ✗ WebUI failed to start"
        cat /tmp/jaeger-webui.log
        kill $GATEWAY_PID $WEBUI_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Create a test instance
 APAecho "→ Creating test instance..."
"$PY" -m jaeger_ai.cli.run agent create --name test --non-interactive 2>/dev/null || true

# Save PIDs for cleanup
echo "$GATEWAY_PID" > /tmp/jaeger-test-gateway.pid
echo "$WEBUI_PID" > /tmp/jaeger-test-webui.pid

echo ""
echo "========================================"
echo "  ✅ Test Environment Running"
echo "========================================"
echo ""
echo "  Gateway:   $GATEWAY_URL"
echo "  WebUI:     $WEBUI_URL"
echo "  WebSocket: ws://127.0.0.1:33418/ws"
echo ""
echo "  Logs:"
echo "    Gateway: /tmp/jaeger-gateway.log"
echo "    WebUI:   /tmp/jaeger-webui.log"
echo ""
echo "  To stop: ./scripts/stop-test-env.sh"
echo ""
