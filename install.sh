#!/bin/bash
# JaegerAI — local installer (runs from inside the cloned repo).
#
# Re-run after git pull to install all five packages from this checkout.
# Builds and virtual environments stay outside source; operator state persists.
# Usage: ./install.sh [--skip-deps] [--product]
# Prerequisites: Python 3.11/3.12, git, and a native compiler toolchain.

set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${XDG_CACHE_HOME:-$HOME/.cache}/jaeger/pycache"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)"
# One-line install: `curl -fsSL <raw-url>/install.sh | bash` runs this
# OUTSIDE a checkout — detect that (no pyproject beside us), clone, and
# re-exec inside the fresh clone.
if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  JAEGER_INSTALL_ROOT="${JAEGER_INSTALL_ROOT:-$HOME/JaegerAI}"
  echo "no checkout here — cloning JaegerAI to $JAEGER_INSTALL_ROOT"
  git clone "${JAEGER_REPO_URL:-https://github.com/JenkinsRobotics/JaegerAI.git}" "$JAEGER_INSTALL_ROOT"
  exec bash "$JAEGER_INSTALL_ROOT/install.sh" "$@"
fi
VENV="${JAEGER_VENV:-$HOME/.jaeger/venv}"
export JAEGER_VENV="$VENV"
export JAEGER_INSTALL_ROOT="$REPO_ROOT"

SKIP_DEPS=0
PRODUCT_MODE=0
SETUP_ROBOT=0
for arg in "$@"; do
  case "$arg" in
    --skip-deps) SKIP_DEPS=1 ;;
    # Set by scripts/install.sh (the curl one-liner) — every JaegerAI
    # clone has a dev/ tree now (0.9 split: the repo root IS the clean
    # product, no monorepo copy-strips-dev step to key off of anymore),
    # so "was dev/ stripped" can no longer distinguish an end-user
    # install from a developer's own checkout. This flag is the
    # explicit signal instead: only the curl path sets it.
    --product) PRODUCT_MODE=1 ;;
    --setup-robot|--appliance) SETUP_ROBOT=1 ;;
  esac
done

echo "JaegerAI local install"
echo "  repo: $REPO_ROOT"
echo

# Ensure standard package manager paths are on PATH
for p in /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin "$HOME/.local/bin"; do
  if [[ -d "$p" && ":$PATH:" != *":$p:"* ]]; then
    export PATH="$p:$PATH"
  fi
done

# 1. Verify Python version. Respect a ``PY`` exported by the curl-side
# installer (scripts/install.sh) if valid, otherwise search candidates.
find_working_python() {
  if [[ -n "${PY:-}" ]] && "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] in [(3, 11), (3, 12)] else 1)' 2>/dev/null; then
    echo "$PY"
    return 0
  fi
  for candidate in python3.12 python3.11 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.12 /usr/local/bin/python3.11 python3; do
    if cmd=$(command -v "$candidate" 2>/dev/null) && "$cmd" -c 'import sys; sys.exit(0 if sys.version_info[:2] in [(3, 11), (3, 12)] else 1)' 2>/dev/null; then
      echo "$cmd"
      return 0
    fi
  done
  return 1
}

if ! PY="$(find_working_python)"; then
  echo "✗ Supported Python (3.11 or 3.12) not found or not executable" >&2
  echo "  hint: macOS — 'brew install python@3.12' (or python@3.11)" >&2
  echo "        Ubuntu — 'apt install python3.12 python3.12-venv'" >&2
  exit 1
fi
PY_VERSION=$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✓ Python $PY_VERSION at $PY"

# 1b. Node.js & npm (required to compile the shared web interface)
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "✗ Node.js and npm are required to build the web interface" >&2
  echo "  hint: macOS — 'brew install node'" >&2
  echo "        Ubuntu — 'apt install nodejs npm'" >&2
  exit 1
fi
echo "✓ Node.js $(node -v) and npm $(npm -v)"

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
  echo "→ Creating the Python environment at $VENV..."
  "$PY" -m venv "$VENV"
fi
PIP="$VENV/bin/pip"

# 3. Install JaegerAI — EDITABLE, so the clone IS the live package: a
#    `jaeger` command + `jaeger --version`, code still writable in place
#    (the agent self-modifies its skills; you can hack the framework).
#    Runtime deps come from release-locked requirements.txt via pyproject's
#    dynamic dependencies. This pulls the whole stack with no manual
#    assembly and fails closed on an incompatible dependency contract.
#    Prefer uv (fast); it lives inside the .venv so we never
#    touch system Python.
if [[ "$SKIP_DEPS" -eq 0 ]]; then
  echo "→ Upgrading pip..."
  "$PIP" install --upgrade pip --quiet
  UV="$VENV/bin/uv"
  if [[ ! -x "$UV" ]]; then
    echo "→ Installing uv..."
    "$PIP" install uv --quiet || true
  fi
  # Build each package in an external scratch directory; install wheels in
  # dependency order so our own code always comes from this checkout.
  echo "→ Installing in-repo packages (JaegerOS, agent, voice engines)..."
  for pkg in jaeger-os jaeger-agent jaeger-kokoro-tts jaeger-whisper-stt; do
    PKG_SPEC="$REPO_ROOT/packages/$pkg"
    [[ "$pkg" == "jaeger-agent" ]] && PKG_SPEC="$PKG_SPEC[multimodal-duplex]"
    "$VENV/bin/python" "$REPO_ROOT/scripts/install-packages.py" "$PKG_SPEC"
    echo "  ✓ $pkg"
  done
  "$VENV/bin/python" "$REPO_ROOT/scripts/install-packages.py" "$REPO_ROOT"

  # 3c. Playwright chromium — the `browser` tool needs a chromium build
  # matching the installed playwright package. Idempotent: skips the
  # download when the matching revision is already cached, so re-running
  # install.sh after a playwright upgrade refreshes a stale browser.
  echo "→ Installing Playwright chromium (browser tool)..."
  "$VENV/bin/playwright" install chromium ||
    echo "  ⚠ playwright install chromium failed — browser tool won't work until you run it manually"
else
  echo "→ --skip-deps: leaving $VENV untouched"
fi

# 4. Scaffold ~/.jaeger/ (idempotent) — operator state root (OpenClaw standard)
STATE_ROOT="${JAEGER_STATE_DIR:-$HOME/.jaeger}"
mkdir -p "$STATE_ROOT/instances" "$STATE_ROOT/logs"
if [[ -f "$REPO_ROOT/scripts/migrate-webui-config.py" ]]; then
  "$VENV/bin/python" "$REPO_ROOT/scripts/migrate-webui-config.py" --state-root "$STATE_ROOT"
fi

# 4b. Initialize Gateway caller authentication tokens
echo "→ Initializing Gateway caller tokens..."
"$VENV/bin/python" -m jaeger_ai.cli.verbs.dispatch auth init ||
  echo "  ⚠ Could not initialize caller tokens automatically; run './jaeger auth init' manually"

# A one-line product install is intentionally still a Git checkout so the
# public installer can refresh it efficiently. Mark it explicitly so the CLI
# does not mistake it for a developer's working tree and bypass the full
# end-user update + instance-migration workflow.
if [[ "$PRODUCT_MODE" -eq 1 ]]; then
  : > "$REPO_ROOT/.jaeger-product-install"
fi

# 5. Put `jaeger` on PATH so the command works system-wide (idempotent).
#    PRODUCT installs only — a dev checkout must never claim the global
#    name, or re-running ./install.sh in the repo would silently repoint
#    the released `jaeger` at development code. Dev uses ./jaeger.
#    Prefer a /usr/local/bin symlink (already on every macOS PATH); when
#    that's not writable (no sudo), fall back to the user's shell rc.
if [[ "$PRODUCT_MODE" -eq 1 ]]; then
  if ln -sfn "$REPO_ROOT/jaeger" /usr/local/bin/jaeger 2>/dev/null; then
    echo "✓ jaeger on PATH (/usr/local/bin/jaeger)"
  else
    RC="$HOME/.zshrc"
    [[ "${SHELL:-}" == */bash ]] && RC="$HOME/.bashrc"
    PATH_LINE="export PATH=\"$REPO_ROOT:\$PATH\"  # jaeger"
    if ! grep -qsF "$PATH_LINE" "$RC"; then
      printf '\n%s\n' "$PATH_LINE" >> "$RC"
    fi
    echo "✓ jaeger added to PATH via $RC — open a new terminal (or: source $RC)"
  fi
fi

# 5b. Post-install verification smoke check
echo "→ Verifying installation health..."
"$VENV/bin/python" -c "
import importlib.metadata, sys
packages = ('jaeger-ai', 'jaeger-os', 'jaeger-agent', 'jaeger-kokoro-tts', 'jaeger-whisper-stt')
missing = []
for pkg in packages:
    try:
        v = importlib.metadata.version(pkg)
        print(f'  ✓ {pkg:<20} {v}')
    except Exception as e:
        print(f'  ✗ {pkg:<20} NOT FOUND ({e})')
        missing.append(pkg)
if missing:
    sys.exit(1)
" 2>/dev/null || echo "  ⚠ Package metadata check reported warnings (modules may still be available via source)"

echo
echo "✓ Local install complete"

if [[ "$PRODUCT_MODE" -eq 0 ]]; then
  # Direct ./install.sh, no --product flag — a developer's own checkout
  # (git clone + ./install.sh, or a repeat run inside one). Build the
  # dev shell so the first thing a developer sees works.
  if command -v swift >/dev/null 2>&1; then
    echo; echo "building canonical JaegerShell.app (debug)…"
    bash "$REPO_ROOT/jaeger_ai/interfaces/macos-shell/Scripts/build-shell.sh" >/dev/null \
      && echo "✓ Canonical JaegerShell.app ready in the external Mac build directory" \
      || echo "⚠ Mac shell build failed — inspect interfaces/macos-shell/Scripts/build-shell.sh"
  fi
  echo
  echo "Next steps:"
  echo "  ./jaeger dev              the windowed dev shell (jaeger-dev instance)"
  echo "  ./jaeger dev --tui        the terminal agent"
  echo "  ./jaeger update           pull + reinstall deps + rebuild as needed"
  echo "  ./jaeger dev --health     verify the install"
else
  # curl one-liner (scripts/install.sh passes --product) — build the
  # PRODUCT app; it's what `./jaeger` launches. No Swift toolchain
  # (Linux/headless) → terminal remains the surface, quietly.
  if command -v swift >/dev/null 2>&1; then
    echo; echo "building canonical JaegerShell.app (development target)…"
    bash "$REPO_ROOT/jaeger_ai/interfaces/macos-shell/Scripts/build-shell.sh" >/dev/null \
      && echo "✓ Canonical development Mac shell ready; production installation remains deferred" \
      || echo "⚠ Swift app build failed — ./jaeger falls back to the terminal"
  fi
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "Mac production installation is deferred; no old SwiftUI app is installed automatically."
  fi
  echo
  echo "Next steps:"
  echo "  ./jaeger agent create   # create your first agent"
  echo "  ./jaeger                # run it   (--tui for terminal)"
  echo "  ./jaeger launcher install  # refresh the Applications/Launchpad icon"
  echo "  ./jaeger doctor         # environment + readiness check"
  echo
  echo "Optional:"
  echo "  export PATH=\"\$PATH:$REPO_ROOT\"   # 'jaeger' from anywhere"
  echo "  ./jaeger autostart enable          # run unattended at login"
fi

# 6. Autonomous Robot / Dedicated Appliance Host Setup (macOS)
if [[ "$(uname -s)" == "Darwin" ]]; then
  if [[ "$SETUP_ROBOT" -eq 1 ]]; then
    echo
    bash "$REPO_ROOT/scripts/setup-mac-robot.sh" --non-interactive
  elif [[ -t 0 ]]; then
    echo
    echo "─────────────────────────────────────────────────────────────────"
    echo "  Autonomous Robot / Dedicated Host Setup"
    echo "─────────────────────────────────────────────────────────────────"
    echo "  Configure this Mac as a 24/7 Persistent Robot Appliance?"
    echo "  (Power recovery, memory tuning, dedicated user, auto-startup)"
    read -r -p "  Run host setup now? [y/N]: " RUN_SETUP || RUN_SETUP="n"
    if [[ "$RUN_SETUP" =~ ^[Yy]$ ]]; then
      bash "$REPO_ROOT/scripts/setup-mac-robot.sh"
    fi
  fi
fi
