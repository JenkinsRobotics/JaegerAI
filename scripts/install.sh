#!/bin/bash
# JROS — one-line installer (builds a CLEAN, product-only install).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JROS/master/scripts/install.sh | bash
#
# Pin to a branch / release:
#   JAEGER_REF=0.5.0 curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JROS/0.5.0/scripts/install.sh | bash
#
# Custom install location:
#   JAEGER_HOME=/opt/jaeger curl -fsSL .../install.sh | bash
#
# What this does:
#   1. Verify prereqs (git, python 3.11/3.12).
#   2. Fetch the JROS repo into a cache ($JAEGER_SRC, default
#      ~/.cache/jaeger-src) — the full dev tree stays there.
#   3. Copy ONLY the product (jaeger_os/ + entry scripts + manifests) into
#      $JAEGER_HOME — so the install dir is clean: no dev/tests/, no
#      benchmarks, no dev launcher, no .git.
#   4. Run the in-repo ./install.sh in $JAEGER_HOME — .venv, deps, and
#      scaffolds $JAEGER_HOME/.jaeger_os/ for instance state.
#   5. Print next steps.
#
# Re-running refreshes the product from the latest ref while leaving the
# install's .venv/ and .jaeger_os/ instance state untouched.

set -euo pipefail

JAEGER_HOME="${JAEGER_HOME:-$HOME/jaeger}"
JAEGER_REF="${JAEGER_REF:-master}"
REPO_URL="${JAEGER_REPO_URL:-https://github.com/JenkinsRobotics/JROS.git}"
JAEGER_SRC="${JAEGER_SRC:-$HOME/.cache/jaeger-src}"
# Raw URL for the upgrade hint (github.com → raw.githubusercontent.com, no .git).
RAW_URL="$(printf '%s' "$REPO_URL" | sed 's#github.com#raw.githubusercontent.com#; s#\.git$##')/$JAEGER_REF/scripts/install.sh"

# The product allowlist — exactly what an end-user install contains.
# Everything else in the repo (dev/ jaeger-studio/ launch_studio
# scripts/ JaegerOS-dev.app) is dev-only and never copied. jaeger_os/ is
# self-contained — it imports none of the dev tree at runtime.
PRODUCT=(
  jaeger_os
  install.sh run.sh jaeger
  requirements.txt pyproject.toml
  jaeger.toml jaeger.windowed.toml
  README.md LICENSE CHANGELOG.md
)

cat <<EOF
╔══════════════════════════════════════════════╗
║  JROS — Jaeger-OS one-line installer         ║
╚══════════════════════════════════════════════╝
  install location: $JAEGER_HOME   (clean: jaeger_os/ + .jaeger_os/)
  source cache:     $JAEGER_SRC
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
    fi ;;
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
    fi ;;
esac

# Python: prefer an explicit 3.12 / 3.11 binary, fall back to python3.
# macOS often has python3 → 3.13 (Xcode/python.org) while the workable
# interpreter is python3.12 from Homebrew; search explicitly.
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
echo "✓ prereqs OK (git, C toolchain, $PY → python$PY_VERSION)"
export PY   # the in-repo install.sh picks up the same interpreter

# 2. Fetch the repo into the source cache (full dev tree lives here, not
#    in the install dir).
if [[ -d "$JAEGER_SRC/.git" ]]; then
  echo "→ updating source cache at $JAEGER_SRC"
  git -C "$JAEGER_SRC" fetch origin --tags --quiet
  git -C "$JAEGER_SRC" checkout "$JAEGER_REF" --quiet
  git -C "$JAEGER_SRC" pull --ff-only origin "$JAEGER_REF" --quiet 2>/dev/null || true
else
  if [[ -e "$JAEGER_SRC" ]]; then
    echo "✗ $JAEGER_SRC exists but is not a git repo — move it aside or set JAEGER_SRC" >&2
    exit 1
  fi
  echo "→ cloning JROS into the source cache ($JAEGER_SRC)"
  mkdir -p "$(dirname "$JAEGER_SRC")"
  git clone --branch "$JAEGER_REF" "$REPO_URL" "$JAEGER_SRC" --quiet
fi

# 3. Assemble the clean install dir from the product allowlist. Refreshes
#    each product item; never touches .venv/ or .jaeger_os/ in the install.
echo "→ assembling clean install at $JAEGER_HOME"
mkdir -p "$JAEGER_HOME"
for item in "${PRODUCT[@]}"; do
  if [[ -e "$JAEGER_SRC/$item" ]]; then
    rm -rf "$JAEGER_HOME/$item"
    cp -R "$JAEGER_SRC/$item" "$JAEGER_HOME/$item"
  fi
done
# Drop any stray bytecode the copy carried along.
find "$JAEGER_HOME/jaeger_os" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# 4. Run the in-repo installer in the clean dir (.venv + deps + scaffold).
echo "→ running local installer..."
bash "$JAEGER_HOME/install.sh"

cat <<EOF

╔══════════════════════════════════════════════╗
║  ✓ JROS installed at $JAEGER_HOME            ║
╚══════════════════════════════════════════════╝

Your install is clean — jaeger_os/ plus the entry scripts; instance state
lives under .jaeger_os/. (The full dev tree stays in the cache,
$JAEGER_SRC — delete it any time.)

Next steps:
  cd $JAEGER_HOME
  ./jaeger agent create    # create your first agent
  ./jaeger                 # run it   (--tui for terminal)

Upgrade later:
  curl -fsSL $RAW_URL | JAEGER_HOME=$JAEGER_HOME JAEGER_REF=$JAEGER_REF bash

EOF
