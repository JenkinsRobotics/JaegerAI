#!/bin/bash
# Stop the JaegerAI test environment
# Usage: ./scripts/stop-test-env.sh

set -euo pipefail

echo "→ Stopping JaegerAI test environment..."

# Kill Gateway
if [ -f /tmp/jaeger-test-gateway.pid ]; then
    GATEWAY_PID=$(cat /tmp/jaeger-test-gateway.pid)
    if kill -0 "$GATEWAY_PID" 2>/dev/null; then
        echo "  Stopping Gateway (PID: $GATEWAY_PID)..."
        kill "$GATEWAY_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$GATEWAY_PID" 2>/dev/null || true
    fi
    rm -f /tmp/jaeger-test-gateway.pid
fi

# Kill WebUI
if [ -f /tmp/jaeger-test-webui.pid ]; then
    WEBUI_PID=$(cat /tmp/jaeger-test-webui.pid)
    if kill -0 "$WEBUI_PID" 2>/dev/null; then
        echo "  Stopping WebUI (PID: $WEBUI_PID)..."
        kill "$WEBUI_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$WEBUI_PID" 2>/dev/null || true
    fi
    rm -f /tmp/jaeger-test-webui.pid
fi

# Also kill any remaining jaeger processes
pkill -f "jaeger_ai.*gateway" 2>/dev/null || true
pkill -f "jaeger_ai.*webui" 2>/dev/null || true

# Clean up test state
if [ -n "${JAEGER_STATE_DIR:-}" ] && [ -d "$JAEGER_STATE_DIR" ]; then
    echo "  Cleaning test state: $JAEGER_STATE_DIR"
    rm -rf "$JAEGER_STATE_DIR"
fi

echo ""
echo "✅ Test environment stopped"
