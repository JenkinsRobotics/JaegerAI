#!/bin/zsh
# Build canonical shared UI from an external snapshot; no source-tree dependencies/output.
set -eu
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$HOME/.cache/jaeger/pycache"
python3 -B "$REPO/jaeger_ai/interfaces/ui/scripts/build-external.py" "$@"
