#!/usr/bin/env bash
# Address a started test supervisor by JAEGER_STATE_DIR or --state-dir.
# No PID files, pkill, operator signals, or state deletion.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
PY="${JAEGER_VENV:-$HOME/.jaeger/venv}/bin/python"
exec "$PY" -B "$REPO_ROOT/scripts/test-stack.py" stop "$@"
