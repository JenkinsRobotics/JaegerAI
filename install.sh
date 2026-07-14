#!/bin/bash
# JaegerAI — local installer (runs from inside the cloned repo).
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
#
# 0.9 four-way split: JaegerAI's own pyproject.toml declares git
# dependencies on jaeger-os / jaeger-kokoro-tts / jaeger-whisper-stt
# (requirements.txt, @master for 0.9) — installing JaegerAI (editable,
# below) pulls the whole stack from GitHub automatically, no manual
# multi-repo assembly needed. A dev machine with sibling checkouts at
# ~/GITHUB/{JaegerOS,JaegerKokoroTTS,JaegerWhisperSTT} gets those
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
#    Runtime deps come from requirements.txt via pyproject's dynamic
#    dependencies — including the jaeger-os / jaeger-kokoro-tts /
#    jaeger-whisper-stt git dependencies (0.9 four-way split): this one
#    install pulls the whole stack from GitHub, no manual multi-repo
#    assembly. Prefer uv (fast); it lives inside the .venv so we never
#    touch system Python.
if [[ "$SKIP_DEPS" -eq 0 ]]; then
  echo "→ Upgrading pip..."
  "$PIP" install --upgrade pip --quiet
  UV="$VENV/bin/uv"
  if [[ ! -x "$UV" ]]; then
    echo "→ Installing uv..."
    "$PIP" install uv --quiet || true
  fi
  if [[ -x "$UV" ]]; then
    echo "→ Installing JaegerAI (editable) via uv..."
    "$UV" pip install --python "$VENV/bin/python" -e "$REPO_ROOT" --quiet
  else
    echo "→ uv unavailable — installing JaegerAI (editable) via pip..."
    "$PIP" install -e "$REPO_ROOT" --quiet
  fi

  # 3b. Dev-clone sibling detection — OPT-IN ONLY (JAEGER_DEV_SIBLINGS=1).
  # On a dev machine you may editable-install ~/GITHUB/{JaegerOS,
  # JaegerKokoroTTS,JaegerWhisperSTT} checkouts OVER the git-resolved
  # copies so local framework/engine changes go live immediately.
  # STATIONS MUST BE HERMETIC: a production install (incl. the 0.8.2
  # migration) must run the OFFICIAL pinned releases inside its own
  # venv — never code linked from someone's working trees, where a
  # half-finished refactor would break the station live. Hence the
  # explicit flag: nobody gets dev wiring by accident of directory
  # layout. (Field-caught by the operator on migration day, 2026-07-12.)
  if [[ "${JAEGER_DEV_SIBLINGS:-0}" != "1" ]]; then
    SIBLING_ROOT=""
  else
    SIBLING_ROOT="${JAEGER_SIBLING_ROOT:-$HOME/GITHUB}"
  fi
  SIBLINGS_FOUND=()
  [[ -n "$SIBLING_ROOT" ]] &&
  for sib in JaegerOS JaegerKokoroTTS JaegerWhisperSTT; do
    if [[ -f "$SIBLING_ROOT/$sib/pyproject.toml" ]]; then
      SIBLINGS_FOUND+=("$sib")
    fi
  done
  if [[ "${#SIBLINGS_FOUND[@]}" -gt 0 ]]; then
    echo "→ dev sibling checkouts found (${SIBLINGS_FOUND[*]}) — installing editable over the git-resolved copies..."
    for sib in "${SIBLINGS_FOUND[@]}"; do
      if [[ -x "$UV" ]]; then
        "$UV" pip install --python "$VENV/bin/python" -e "$SIBLING_ROOT/$sib" --quiet
      else
        "$PIP" install -e "$SIBLING_ROOT/$sib" --quiet
      fi
      echo "  ✓ $sib (editable, from $SIBLING_ROOT/$sib)"
    done
  fi

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

# 4. Scaffold .jaeger_os/ (idempotent) — operator state root
mkdir -p "$REPO_ROOT/.jaeger_os/instances"

echo
echo "✓ Local install complete"

if [[ "$PRODUCT_MODE" -eq 0 ]]; then
  # Direct ./install.sh, no --product flag — a developer's own checkout
  # (git clone + ./install.sh, or a repeat run inside one). Build the
  # dev shell so the first thing a developer sees works.
  if command -v swift >/dev/null 2>&1; then
    echo; echo "building JaegerOS.app (debug)…"
    "$REPO_ROOT/jaeger_ai/interfaces/swift/Scripts/build-app.sh" --dev >/dev/null \
      && echo "✓ JaegerOS.app ready (symlinked at repo root)" \
      || echo "⚠ Swift app build failed — run Scripts/build-app.sh --dev later"
  fi
  echo
  echo "Next steps:"
  echo "  ./jaeger dev              the windowed dev shell (jros-dev instance)"
  echo "  ./jaeger dev --tui        the terminal agent"
  echo "  ./jaeger update           pull + reinstall deps + rebuild as needed"
  echo "  ./jaeger dev --health     verify the install"
else
  # curl one-liner (scripts/install.sh passes --product) — build the
  # PRODUCT app; it's what `./jaeger` launches. No Swift toolchain
  # (Linux/headless) → terminal remains the surface, quietly.
  if command -v swift >/dev/null 2>&1; then
    echo; echo "building JaegerOS.app (first build takes a minute)…"
    "$REPO_ROOT/jaeger_ai/interfaces/swift/Scripts/build-app.sh" --release >/dev/null \
      && echo "✓ JaegerOS.app ready" \
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
