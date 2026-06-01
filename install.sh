#!/bin/bash
# JROS — local installer (runs from inside the cloned repo).
#
# Idempotent — safe to re-run after a `git pull`:
#   - first run:  creates .venv, installs dependencies, scaffolds agents/
#   - re-run:     upgrades dependencies, leaves agents/ alone
#
# Usage:
#   ./install.sh                  # default — runs all steps
#   ./install.sh --skip-deps      # only scaffold; don't touch .venv
#
# Prereqs: python3 (3.11 or 3.12), git.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_ROOT/.venv"

SKIP_DEPS=0
for arg in "$@"; do
  case "$arg" in
    --skip-deps) SKIP_DEPS=1 ;;
  esac
done

echo "JROS local install"
echo "  repo: $REPO_ROOT"
echo

# 1. Verify Python version
PY="$(command -v python3.12 || command -v python3.11 || command -v python3)"
if [[ -z "${PY:-}" ]]; then
  echo "✗ python3 not found — install Python 3.11 or 3.12 first" >&2
  exit 1
fi
PY_VERSION=$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
case "$PY_VERSION" in
  3.11|3.12) echo "✓ Python $PY_VERSION at $PY" ;;
  *)
    echo "✗ Python $PY_VERSION not supported — need 3.11 or 3.12" >&2
    exit 1
    ;;
esac

# 2. Create or reuse the .venv
if [[ ! -d "$VENV" ]]; then
  echo "→ Creating .venv..."
  "$PY" -m venv "$VENV"
fi
PIP="$VENV/bin/pip"

# 3. Install dependencies
if [[ "$SKIP_DEPS" -eq 0 ]]; then
  echo "→ Upgrading pip..."
  "$PIP" install --upgrade pip --quiet
  echo "→ Installing dependencies..."
  "$PIP" install -r "$REPO_ROOT/requirements.txt" --quiet
else
  echo "→ --skip-deps: leaving .venv untouched"
fi

# 4. Scaffold agents/ (idempotent)
mkdir -p "$REPO_ROOT/src/jaeger_os/agents"

# 5. Ensure ~/.jaeger/ exists for runtime instance state
mkdir -p "$HOME/.jaeger/instances"

echo
echo "✓ Local install complete"
echo
echo "Next steps:"
echo "  ./run.sh              # launches the agent"
echo "  ./run.sh --setup      # runs the first-time wizard"
echo
echo "Optional — add to your shell rc for global access:"
echo "  export PATH=\"\$PATH:$REPO_ROOT\""
