#!/bin/bash
# JaegerAI — one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/master/scripts/install.sh | bash
#
# Pin to a branch / release:
#   JAEGER_REF=0.9.0 curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/0.9.0/scripts/install.sh | bash
#
# Custom install location:
#   JAEGER_HOME=/opt/jaeger curl -fsSL .../install.sh | bash
#
# What this does:
#   1. Verify prereqs (git, python 3.11/3.12, C toolchain).
#   2. Clone (or update) the JaegerAI repo into $JAEGER_HOME — the repo
#      root IS the clean product (0.9 four-way split: JaegerAI is its
#      own top-level package + pyproject.toml, no monorepo assembly
#      step needed).
#   3. Run the in-repo ./install.sh — .venv, deps (pyproject's git
#      dependencies pull jaeger-os / jaeger-kokoro-tts /
#      jaeger-whisper-stt straight from GitHub — one install resolves
#      the whole 4-package stack), app build, scaffold $JAEGER_HOME/
#      .jaeger_os/ for instance state.
#   4. Print next steps.
#
# Re-running refreshes JaegerAI from the latest ref (git pull + editable
# reinstall) while leaving .venv/ and .jaeger_os/ instance state
# untouched.

set -euo pipefail

JAEGER_HOME="${JAEGER_HOME:-$HOME/jaeger}"
JAEGER_REF="${JAEGER_REF:-master}"
REPO_URL="${JAEGER_REPO_URL:-https://github.com/JenkinsRobotics/JaegerAI.git}"
# Raw URL for the upgrade hint (github.com → raw.githubusercontent.com, no .git).
RAW_URL="$(printf '%s' "$REPO_URL" | sed 's#github.com#raw.githubusercontent.com#; s#\.git$##')/$JAEGER_REF/scripts/install.sh"

cat <<EOF
╔══════════════════════════════════════════════╗
║  JaegerAI — one-line installer                ║
╚══════════════════════════════════════════════╝
  install location: $JAEGER_HOME
  ref:              $JAEGER_REF

EOF

# 1. Prereqs — git is required
if ! command -v git >/dev/null 2>&1; then
  echo "✗ 'git' not found in PATH — install it first" >&2
  exit 1
fi

# C toolchain — several deps (msgspec, llama-cpp-python, …) build from source.
# Fail early with the exact per-OS fix instead of a half-built .venv later.
case "$(uname -s)" in
  Darwin)
    if ! xcode-select -p >/dev/null 2>&1; then
      echo "✗ Xcode Command Line Tools not found (needed to build deps)" >&2
      echo "  fix: xcode-select --install" >&2
      exit 1
    fi
    # Swift toolchain — optional (the windowed app build). No Swift →
    # ./install.sh quietly skips the app build and falls back to the
    # terminal; not fatal, but worth a loud heads-up so it isn't a
    # silent surprise.
    if ! command -v swift >/dev/null 2>&1; then
      echo "⚠ Swift toolchain not found — the windowed app won't build" >&2
      echo "  fix: install Xcode (App Store) for the full GUI, or ignore — the terminal (--tui) always works" >&2
    fi
    ;;
  Linux)
    if ! command -v cc >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1 \
       && ! command -v clang >/dev/null 2>&1; then
      echo "✗ No C compiler (cc/gcc/clang) found — needed to build deps" >&2
      echo "  fix: Ubuntu — sudo apt install build-essential" >&2
      echo "       Fedora — sudo dnf groupinstall 'Development Tools'" >&2
      exit 1
    fi
    # PortAudio — sounddevice needs libportaudio for voice (non-fatal).
    if command -v ldconfig >/dev/null 2>&1 \
       && ! ldconfig -p 2>/dev/null | grep -q portaudio; then
      echo "⚠ libportaudio not found — voice (mic/speaker) will be unavailable" >&2
      echo "  fix: Ubuntu — sudo apt install libportaudio2" >&2
    fi
    ;;
esac

# Python: prefer an explicit 3.12 / 3.11 binary, fall back to python3.
# macOS often has python3 → 3.13 (Xcode/python.org) while the workable
# interpreter is python3.12 from Homebrew; search explicitly. kokoro/
# whisper (the voice engines) pin <3.13 — 3.13 resolves but can't
# actually install the voice stack, so it's rejected here too.
PY="$(command -v python3.12 || command -v python3.11 || command -v python3 || true)"
if [[ -z "$PY" ]]; then
  echo "✗ No python3.12 / python3.11 / python3 found on PATH" >&2
  echo "  hint: macOS — 'brew install python@3.12'" >&2
  echo "        Ubuntu — 'apt install python3.12 python3.12-venv'" >&2
  exit 1
fi
PY_VERSION=$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
case "$PY_VERSION" in
  3.11|3.12) ;;
  *)
    echo "✗ Python $PY_VERSION at $PY is not supported (need 3.11 or 3.12)" >&2
    echo "  hint: macOS — 'brew install python@3.12'" >&2
    echo "        Ubuntu — 'apt install python3.12 python3.12-venv'" >&2
    exit 1
    ;;
esac

# Disk space — the model + voice/vision weights are multi-GB; fail loud
# rather than 90% through a download.
if command -v df >/dev/null 2>&1; then
  AVAIL_KB=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')
  if [[ -n "${AVAIL_KB:-}" && "$AVAIL_KB" -lt 15000000 ]]; then
    AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
    echo "⚠ only ~${AVAIL_GB}GB free at \$HOME — a local GGUF model + voice/vision" >&2
    echo "  weights typically need 10-20GB+. Free up space or point at a bigger" >&2
    echo "  volume before continuing." >&2
  fi
fi

echo "✓ prereqs OK (git, C toolchain, $PY → python$PY_VERSION)"
export PY   # the in-repo install.sh picks up the same interpreter

# 2. Clone (or update) JaegerAI directly into the install dir — the repo
#    root already IS the clean product (0.9 split; no monorepo copy step).
if [[ -d "$JAEGER_HOME/.git" ]]; then
  echo "→ updating $JAEGER_HOME"
  git -C "$JAEGER_HOME" fetch origin --tags --quiet
  git -C "$JAEGER_HOME" checkout "$JAEGER_REF" --quiet
  git -C "$JAEGER_HOME" pull --ff-only origin "$JAEGER_REF" --quiet 2>/dev/null || true
else
  if [[ -e "$JAEGER_HOME" ]]; then
    echo "✗ $JAEGER_HOME exists but is not a git repo — move it aside or set JAEGER_HOME" >&2
    exit 1
  fi
  echo "→ cloning JaegerAI into $JAEGER_HOME"
  mkdir -p "$(dirname "$JAEGER_HOME")"
  git clone --branch "$JAEGER_REF" "$REPO_URL" "$JAEGER_HOME" --quiet
fi

# 3. Run the in-repo installer (.venv + deps incl. the git-resolved
#    jaeger-os/jaeger-kokoro-tts/jaeger-whisper-stt stack + app build +
#    .jaeger_os/ scaffold). --product tells it this is an end-user
#    install (build the release app, not the dev shell) — every clone
#    has a dev/ tree now (0.9 split), so that can no longer be the
#    dev-vs-product signal on its own.
echo "→ running local installer..."
bash "$JAEGER_HOME/install.sh" --product

cat <<EOF

╔══════════════════════════════════════════════╗
║  ✓ JaegerAI installed at $JAEGER_HOME
╚══════════════════════════════════════════════╝

Instance state lives under .jaeger_os/; the code stays writable in
place (editable install — the agent self-modifies its own skills).

Next steps:
  cd $JAEGER_HOME
  ./jaeger agent create    # create your first agent
  ./jaeger                 # run it   (--tui for terminal)
  ./jaeger doctor          # environment + readiness check

Upgrade later:
  curl -fsSL $RAW_URL | JAEGER_HOME=$JAEGER_HOME JAEGER_REF=$JAEGER_REF bash

EOF
