#!/bin/bash
# JROS — one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JROS/master/scripts/install.sh | bash
#
# Pin to a specific release:
#   JAEGER_REF=0.2.3 curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JROS/0.2.3/scripts/install.sh | bash
#
# Custom install location:
#   JAEGER_HOME=/opt/jaeger curl -fsSL .../install.sh | bash
#
# What this does:
#   1. Verify prereqs (git, python 3.11/3.12).
#   2. Clone JROS to $JAEGER_HOME (default ~/jaeger).
#   3. Run the in-repo ./install.sh — creates .venv, installs deps,
#      scaffolds src/jaeger_os/agents/, ensures ~/.jaeger/ exists.
#   4. Print next-step instructions.
#
# Idempotent: re-running on an existing clone runs `git pull` and
# re-invokes the local installer.

set -euo pipefail

JAEGER_HOME="${JAEGER_HOME:-$HOME/jaeger}"
JAEGER_REF="${JAEGER_REF:-master}"
REPO_URL="${JAEGER_REPO_URL:-https://github.com/JenkinsRobotics/JROS.git}"

cat <<EOF
╔══════════════════════════════════════════════╗
║  JROS — Jaeger-OS one-line installer         ║
╚══════════════════════════════════════════════╝
  install location: $JAEGER_HOME
  ref:              $JAEGER_REF
  repo:             $REPO_URL

EOF

# 1. Prereqs
for cmd in git python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "✗ '$cmd' not found in PATH — install it first" >&2
    exit 1
  fi
done

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
case "$PY_VERSION" in
  3.11|3.12) ;;
  *)
    echo "✗ Python $PY_VERSION not supported (need 3.11 or 3.12)" >&2
    echo "  hint: macOS — 'brew install python@3.12'" >&2
    echo "        Ubuntu — 'apt install python3.12 python3.12-venv'" >&2
    exit 1
    ;;
esac
echo "✓ prereqs OK (git, python$PY_VERSION)"

# 2. Clone (or update existing)
if [[ -d "$JAEGER_HOME/.git" ]]; then
  echo "→ existing clone found at $JAEGER_HOME — updating"
  cd "$JAEGER_HOME"
  git fetch origin --tags
  git checkout "$JAEGER_REF"
  # `git pull` fails on a detached HEAD (tag checkout), which is fine
  # — the checkout above already moved us to the right ref.
  git pull --ff-only origin "$JAEGER_REF" 2>/dev/null || true
else
  if [[ -e "$JAEGER_HOME" ]]; then
    echo "✗ $JAEGER_HOME exists but is not a git repo — refusing to overwrite" >&2
    echo "  move it aside or set JAEGER_HOME to a different path" >&2
    exit 1
  fi
  echo "→ cloning JROS to $JAEGER_HOME"
  git clone --branch "$JAEGER_REF" "$REPO_URL" "$JAEGER_HOME"
  cd "$JAEGER_HOME"
fi

# 3. Run the local installer (venv + deps + scaffolding)
echo "→ running local installer..."
bash "$JAEGER_HOME/install.sh"

cat <<EOF

╔══════════════════════════════════════════════╗
║  ✓ JROS installed at $JAEGER_HOME            ║
╚══════════════════════════════════════════════╝

Next steps:
  cd $JAEGER_HOME
  ./run.sh --setup        # first-time wizard (memory tier, model choice)
  ./run.sh                # launch the agent

Useful commands:
  ./run.sh start          # daemonised background agent
  ./run.sh status         # daemon status
  git pull && ./install.sh   # upgrade JROS

Per-agent workspaces live at:
  $JAEGER_HOME/src/jaeger_os/agents/<name>/

Runtime state (memory, daemon socket, logs):
  ~/.jaeger/instances/<name>/

Optional — add JROS to your PATH:
  echo 'export PATH="\$PATH:$JAEGER_HOME"' >> ~/.zshrc

EOF
