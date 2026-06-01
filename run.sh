#!/bin/bash
# JROS launcher — activates the venv and invokes the agent.
#
# Usage:
#   ./run.sh                  # interactive TUI
#   ./run.sh --force          # re-run the first-time wizard
#   ./run.sh start            # daemonised background agent
#   ./run.sh status           # daemon status
#   …all flags forward to src/jaeger_os/run.py
#
# This script is the supported entry point in the git-clone install model
# (see scripts/install.sh). The `jaeger` / `jaeger-os` console scripts from
# the old pip-install era have been retired.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_ROOT/.venv"

if [[ ! -d "$VENV" ]]; then
  echo "✗ .venv not found at $VENV" >&2
  echo "  run ./install.sh first" >&2
  exit 1
fi

# Activate venv so child processes (browser, MCP servers) inherit it
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Put src/ on PYTHONPATH so `jaeger_os` is importable without an
# `editable install`. Idempotent: only prepend if not already there.
SRC="$REPO_ROOT/src"
case ":${PYTHONPATH:-}:" in
  *":$SRC:"*) ;;
  *) export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

exec python "$REPO_ROOT/src/jaeger_os/run.py" "$@"
