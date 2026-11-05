#!/usr/bin/env bash
# Foreground, isolated test stack. Build UI externally, then set
# JAEGER_WEBUI_UI_DIST. Optional JAEGER_STATE_DIR must be new and disposable.
# Ctrl-C or stop-test-env.sh shuts down only this supervisor's children.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
PY="${JAEGER_VENV:-$HOME/.jaeger/venv}/bin/python"
exec "$PY" -B "$REPO_ROOT/scripts/test-stack.py" start "$@"
