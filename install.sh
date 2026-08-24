#!/bin/bash
# JaegerAI — local installer (runs from inside the cloned repo).
#
# Idempotent — safe to re-run after a `git pull`:
#   - first run:  creates .venv, installs dependencies, scaffolds .jaeger_ai/
#   - re-run:     upgrades dependencies, leaves .jaeger_ai/ alone
#
# Usage:
#   ./install.sh                  # default — runs all steps
#   ./install.sh --skip-deps      # only scaffold; don't touch .venv
#
# Prereqs: python3 (3.11 or 3.12), git.
#
# 0.9 four-way split: JaegerAI's own pyproject.toml declares git
# dependencies on jaeger-os / jaeger-kokoro-tts / jaeger-whisper-stt
# (requirements.txt, release-locked for 0.9) — installing JaegerAI (editable,
# below) pulls the whole stack from GitHub automatically, no manual
# multi-repo assembly needed. A dev machine with sibling checkouts at
# ~/GITHUB/{JaegerOS,jaeger-agent,JaegerKokoroTTS,JaegerWhisperSTT} gets those
# installed EDITABLE instead (step 3b below) — local changes to the
# framework/engines are live without a push+reinstall round-trip.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)"
# One-line install: `curl -fsSL <raw-url>/install.sh | bash` runs this
# OUTSIDE a checkout — detect that (no pyproject beside us), clone, and
# re-exec inside the fresh clone.
if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  JAEGER_HOME="${JAEGER_HOME:-$HOME/jaeger}"
  echo "no checkout here — cloning JaegerAI to $JAEGER_HOME"
  git clone "${JAEGER_REPO_URL:-https://github.com/JenkinsRobotics/JaegerAI.git}" "$JAEGER_HOME"
  exec bash "$JAEGER_HOME/install.sh" "$@"
fi
VENV="$REPO_ROOT/.venv"

SKIP_DEPS=0
PRODUCT_MODE=0
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
  esac
done

echo "JaegerAI local install"
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
  # 3a. In-repo packages FIRST. JaegerOS, jaeger-agent and the two voice
  # engines live at packages/ and are installed from those paths before the
  # root package resolves its own requirements. Order matters: jaeger-agent
  # and the engines each require `jaeger-os`, and installing JaegerOS first
  # means that requirement is already satisfied locally rather than sending
  # pip to the network. Editable so a change under packages/ is live without
  # a reinstall — they are this repository's own source now, not third-party
  # pins, so the hermetic-station argument below does not apply to them.
  echo "→ Installing in-repo packages (JaegerOS, agent, voice engines)..."
  for pkg in jaeger-os jaeger-agent jaeger-kokoro-tts jaeger-whisper-stt; do
    PKG_DIR="$REPO_ROOT/packages/$pkg"
    if [[ ! -f "$PKG_DIR/pyproject.toml" ]]; then
      echo "  ✗ packages/$pkg is missing — the checkout is incomplete" >&2
      exit 1
    fi
    if [[ -x "$UV" ]]; then
      "$UV" pip install --python "$VENV/bin/python" -e "$PKG_DIR" --quiet
    else
      "$PIP" install -e "$PKG_DIR" --quiet
    fi
    echo "  ✓ $pkg"
  done

  if [[ -x "$UV" ]]; then
    echo "→ Installing JaegerAI (editable) via uv..."
    "$UV" pip install --python "$VENV/bin/python" -e "$REPO_ROOT" --quiet
  else
    echo "→ uv unavailable — installing JaegerAI (editable) via pip..."
    "$PIP" install -e "$REPO_ROOT" --quiet
  fi

  # 3b. Sibling-checkout detection: REMOVED in the monorepo absorption.
  # It used to editable-install ~/GITHUB/{JaegerOS,jaeger-agent,
  # JaegerKokoroTTS,JaegerWhisperSTT} over the git-resolved copies so local
  # framework changes went live. That override now has nothing to override:
  # those four ARE this repository, installed editable from packages/ in 3a,
  # so edits are already live. Worse, keeping it would let a stale sibling
  # checkout silently shadow the in-repo source — the exact ambiguity this
  # restructure removed. Point JAEGER_SIBLING_ROOT at nothing; edit
  # packages/ instead.

  # 3c. Playwright chromium — the `browser` tool needs a chromium build
  # matching the installed playwright package. Idempotent: skips the
  # download when the matching revision is already cached, so re-running
  # install.sh after a playwright upgrade refreshes a stale browser.
  echo "→ Installing Playwright chromium (browser tool)..."
  "$VENV/bin/playwright" install chromium ||
    echo "  ⚠ playwright install chromium failed — browser tool won't work until you run it manually"
else
  echo "→ --skip-deps: leaving .venv untouched"
fi

# 4. Scaffold .jaeger_ai/ (idempotent) — operator state root
mkdir -p "$REPO_ROOT/.jaeger_ai/instances"

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

echo
echo "✓ Local install complete"

if [[ "$PRODUCT_MODE" -eq 0 ]]; then
  # Direct ./install.sh, no --product flag — a developer's own checkout
  # (git clone + ./install.sh, or a repeat run inside one). Build the
  # dev shell so the first thing a developer sees works.
  if command -v swift >/dev/null 2>&1; then
    echo; echo "building JaegerAI.app (debug)…"
    "$REPO_ROOT/jaeger_ai/interfaces/swift/Scripts/build-app.sh" --dev >/dev/null \
      && echo "✓ JaegerAI.app ready (symlinked at repo root)" \
      || echo "⚠ Swift app build failed — run Scripts/build-app.sh --dev later"
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
    echo; echo "building JaegerAI.app (first build takes a minute)…"
    "$REPO_ROOT/jaeger_ai/interfaces/swift/Scripts/build-app.sh" --release >/dev/null \
      && echo "✓ JaegerAI.app ready" \
      || echo "⚠ Swift app build failed — ./jaeger falls back to the terminal"
  fi
  echo
  echo "Next steps:"
  echo "  ./jaeger agent create   # create your first agent"
  echo "  ./jaeger                # run it   (--tui for terminal)"
  echo "  ./jaeger doctor         # environment + readiness check"
  echo
  echo "Optional:"
  echo "  export PATH=\"\$PATH:$REPO_ROOT\"   # 'jaeger' from anywhere"
  echo "  ./jaeger autostart enable          # run unattended at login"
fi
