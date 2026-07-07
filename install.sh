#!/bin/bash
# JROS — local installer (runs from inside the cloned repo).
#
# Idempotent — safe to re-run after a `git pull`:
#   - first run:  creates .venv, installs dependencies, scaffolds .jaeger_os/
#   - re-run:     upgrades dependencies, leaves .jaeger_os/ alone
#
# Usage:
#   ./install.sh                  # default — runs all steps
#   ./install.sh --skip-deps      # only scaffold; don't touch .venv
#
# Prereqs: python3 (3.11 or 3.12), git.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)"
# One-line install: `curl -fsSL <raw-url>/install.sh | bash` runs this
# OUTSIDE a checkout — detect that (no pyproject beside us), clone, and
# re-exec inside the fresh clone.
if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  JROS_HOME="${JROS_HOME:-$HOME/GITHUB/JROS}"
  echo "no checkout here — cloning JROS to $JROS_HOME"
  git clone "${JROS_REPO_URL:-https://github.com/Jenkins-Robotics/JROS.git}" "$JROS_HOME"
  exec bash "$JROS_HOME/install.sh" "$@"
fi
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

# 1. Verify Python version. Respect a ``PY`` exported by the curl-side
# installer (scripts/install.sh) — it already did the explicit-version
# search and we don't want to disagree. Fall back to our own search
# when invoked directly (``./install.sh`` from a fresh clone).
PY="${PY:-$(command -v python3.12 || command -v python3.11 || command -v python3 || true)}"
if [[ -z "${PY:-}" ]]; then
  echo "✗ python3 not found — install Python 3.11 or 3.12 first" >&2
  echo "  hint: macOS — 'brew install python@3.12'" >&2
  echo "        Ubuntu — 'apt install python3.12 python3.12-venv'" >&2
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

# C toolchain — deps (msgspec, llama-cpp-python, …) build from source. Mirrors
# the curl-side check in scripts/install.sh, for the direct `./install.sh` path.
case "$(uname -s)" in
  Darwin)
    if ! xcode-select -p >/dev/null 2>&1; then
      echo "✗ Xcode Command Line Tools not found (needed to build deps)" >&2
      echo "  fix: xcode-select --install" >&2
      exit 1
    fi ;;
  Linux)
    if ! command -v cc >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1 \
       && ! command -v clang >/dev/null 2>&1; then
      echo "✗ No C compiler (cc/gcc/clang) — needed to build deps" >&2
      echo "  fix: Ubuntu — sudo apt install build-essential" >&2
      exit 1
    fi ;;
esac

# 2. Create or reuse the .venv
if [[ ! -d "$VENV" ]]; then
  echo "→ Creating .venv..."
  "$PY" -m venv "$VENV"
fi
PIP="$VENV/bin/pip"

# 3. Install JROS — EDITABLE, so the clone IS the live package: a `jaeger`
#    command + `jaeger --version`, code still writable in place (the agent
#    self-modifies its skills; you can hack the framework). Runtime deps come
#    from requirements.txt via pyproject's dynamic dependencies. Prefer uv
#    (fast); it lives inside the .venv so we never touch system Python.
if [[ "$SKIP_DEPS" -eq 0 ]]; then
  echo "→ Upgrading pip..."
  "$PIP" install --upgrade pip --quiet
  UV="$VENV/bin/uv"
  if [[ ! -x "$UV" ]]; then
    echo "→ Installing uv..."
    "$PIP" install uv --quiet || true
  fi
  if [[ -x "$UV" ]]; then
    echo "→ Installing JROS (editable) via uv..."
    "$UV" pip install --python "$VENV/bin/python" -e "$REPO_ROOT" --quiet
  else
    echo "→ uv unavailable — installing JROS (editable) via pip..."
    "$PIP" install -e "$REPO_ROOT" --quiet
  fi
else
  echo "→ --skip-deps: leaving .venv untouched"
fi

# 4. Scaffold .jaeger_os/ (idempotent) — operator state root
mkdir -p "$REPO_ROOT/.jaeger_os/instances"

echo
echo "✓ Local install complete"

# Two audiences, one script: a git checkout has the dev tree (dev/); the
# clean end-user install assembled by scripts/install.sh never does.
if [[ -d "$REPO_ROOT/dev" ]]; then
  # Dev checkout — build the dev shell so the first thing a developer
  # sees works.
  if command -v swift >/dev/null 2>&1; then
    echo; echo "building JaegerOS-dev.app…"
    "$REPO_ROOT/jaeger_os/interfaces/swift/Scripts/build-app.sh" --dev >/dev/null \
      && echo "✓ JaegerOS-dev.app ready (symlinked at repo root)" \
      || echo "⚠ Swift app build failed — run Scripts/build-app.sh --dev later"
  fi
  echo
  echo "Next steps:"
  echo "  open JaegerOS-dev.app     the windowed dev shell (menu-bar tray)"
  echo "  ./jaeger dev --tui        the terminal agent"
  echo "  ./jaeger update           pull + reinstall deps + rebuild as needed"
  echo "  ./jaeger dev --health     verify the install"
else
  # End-user install — build the PRODUCT app; it's what `./jaeger`
  # launches. No Swift toolchain (Linux/headless) → terminal remains
  # the surface, quietly.
  if command -v swift >/dev/null 2>&1; then
    echo; echo "building JaegerOS.app (first build takes a minute)…"
    "$REPO_ROOT/jaeger_os/interfaces/swift/Scripts/build-app.sh" --release >/dev/null \
      && echo "✓ JaegerOS.app ready" \
      || echo "⚠ Swift app build failed — ./jaeger falls back to the terminal"
  fi
  echo
  echo "Next steps:"
  echo "  ./jaeger agent create   # create your first agent"
  echo "  ./jaeger                # run it   (--tui for terminal)"
  echo
  echo "Optional:"
  echo "  export PATH=\"\$PATH:$REPO_ROOT\"   # 'jaeger' from anywhere"
  echo "  ./jaeger autostart enable          # run unattended at login"
fi
