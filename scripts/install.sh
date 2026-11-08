#!/bin/bash
# JaegerAI — one-line installer.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/master/scripts/install.sh | bash
#
# Pin to a branch / release:
#   JAEGER_REF=0.9.0 curl -fsSL https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/0.9.0/scripts/install.sh | bash
#
# Custom checkout: JAEGER_INSTALL_ROOT=/opt/JaegerAI
# Runtime state: JAEGER_STATE_DIR (or JAEGER_HOME), default ~/.jaeger.
# Clones the source, installs the monorepo packages, and builds the native app.
# Re-running updates the selected ref while keeping operator state external.

set -euo pipefail

# Ensure standard package manager paths are on PATH
for p in /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin "$HOME/.local/bin"; do
  if [[ -d "$p" && ":$PATH:" != *":$p:"* ]]; then
    export PATH="$p:$PATH"
  fi
done

# Since 0.12 the product name and default folder agree: Jaeger AI lives at
# ~/JaegerAI. 0.9.x used ~/jaeger. A normal install detects that legacy tree,
# copies its operator state after the new checkout is created, and leaves the
# old tree untouched as a rollback copy. Explicit JAEGER_INSTALL_ROOT always wins.
JAEGER_INSTALL_ROOT_WAS_SET=0
[[ -n "${JAEGER_INSTALL_ROOT+x}" ]] && JAEGER_INSTALL_ROOT_WAS_SET=1
JAEGER_INSTALL_ROOT="${JAEGER_INSTALL_ROOT:-$HOME/JaegerAI}"
LEGACY_JAEGER_HOME="${JAEGER_LEGACY_HOME:-$HOME/jaeger}"
JAEGER_STATE_DEST="${JAEGER_STATE_DIR:-${JAEGER_HOME:-$HOME/.jaeger}}"
MIGRATE_LEGACY=0
if [[ "$JAEGER_INSTALL_ROOT_WAS_SET" -eq 0 \
      && "${JAEGER_MIGRATE_LEGACY:-1}" != "0" \
      && ! -e "$JAEGER_STATE_DEST" \
      && -d "$LEGACY_JAEGER_HOME/.jaeger_os" ]]; then
  # Also resume after a clone succeeded but state copying was interrupted.
  # Never overwrite a target that already has its own operator-state root.
  if [[ ! -e "$JAEGER_INSTALL_ROOT" \
        || (-d "$JAEGER_INSTALL_ROOT/.git" && ! -e "$JAEGER_STATE_DEST") ]]; then
    MIGRATE_LEGACY=1
  fi
fi
JAEGER_REF="${JAEGER_REF:-stable}"
REPO_URL="${JAEGER_REPO_URL:-https://github.com/JenkinsRobotics/JaegerAI.git}"
# Raw URL for the upgrade hint (github.com → raw.githubusercontent.com, no .git).

cat <<EOF
╔══════════════════════════════════════════════╗
║  JaegerAI — one-line installer                ║
╚══════════════════════════════════════════════╝
  install location: $JAEGER_INSTALL_ROOT
  ref:              $JAEGER_REF

EOF

if [[ "$MIGRATE_LEGACY" -eq 1 ]]; then
  echo "  legacy install:  $LEGACY_JAEGER_HOME"
  echo "  migration:       instances + settings → $JAEGER_STATE_DEST"
  echo

  # Never copy live SQLite/WAL state. Match commands that START inside the
  # legacy tree; unlike a broad pgrep, this does not match this installer just
  # because the legacy path appears in its environment or arguments.
  # macOS may report /private/var paths through their /var alias in `ps`.
  LEGACY_PROCESS_ALIAS="${LEGACY_JAEGER_HOME#/private}"
  LEGACY_PROCESS="$(ps -axo pid=,command= 2>/dev/null | while read -r pid command; do
    if [[ "$command" == "$LEGACY_JAEGER_HOME/"* \
          || ("$LEGACY_PROCESS_ALIAS" != "$LEGACY_JAEGER_HOME" \
              && "$command" == "$LEGACY_PROCESS_ALIAS/"*) ]]; then
      printf '%s %s\n' "$pid" "$command"
      # Drain the process table: an early break can SIGPIPE ps under pipefail
      # and exit before explaining why migration was refused.
    fi
  done)"
  if [[ -n "$LEGACY_PROCESS" ]]; then
    echo "✗ Jaeger AI 0.9 is still running from $LEGACY_JAEGER_HOME" >&2
    echo "  Quit the old app, then run this installer again." >&2
    echo "  running: $LEGACY_PROCESS" >&2
    exit 1
  fi
fi

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

# Python: prefer an explicit working 3.12 / 3.11 binary, fall back to python3.
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
export PY
PY_VERSION=$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✓ Python $PY_VERSION at $PY"

# Node.js & npm (required to compile the shared web interface)
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "✗ Node.js and npm are required to build the web interface" >&2
  echo "  hint: macOS — 'brew install node'" >&2
  echo "        Ubuntu — 'apt install nodejs npm'" >&2
  exit 1
fi
echo "✓ Node.js $(node -v) and npm $(npm -v)"

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

# Resolve the product default through a published stable release, not a moving
# development branch. Explicit JAEGER_REF=master opts into development.
if [[ "$JAEGER_REF" == stable ]]; then
  JAEGER_REF="$("$PY" - "$REPO_URL" <<'PYTHON'
import json, sys, urllib.parse, urllib.request
url = urllib.parse.urlparse(sys.argv[1])
if url.hostname != 'github.com':
    raise SystemExit('Set JAEGER_REF explicitly for a non-GitHub source')
repo = url.path.strip('/').removesuffix('.git')
request = urllib.request.Request(f'https://api.github.com/repos/{repo}/releases/latest',
    headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'jaeger-install'})
with urllib.request.urlopen(request, timeout=30) as response:
    release = json.load(response)
tag = release.get('tag_name')
if release.get('draft') or release.get('prerelease') or not isinstance(tag, str) or not tag or tag.startswith('-'):
    raise SystemExit('No published stable release available')
print(tag)
PYTHON
)"
fi
RAW_URL="$(printf '%s' "$REPO_URL" | sed 's#github.com#raw.githubusercontent.com#; s#\.git$##')/$JAEGER_REF/scripts/install.sh"
[[ "$JAEGER_REF" != -* ]] || { echo "Invalid JAEGER_REF" >&2; exit 1; }

# 2. Clone or select an immutable commit. Existing installs use the canonical
# updater (including its service preflight and rollback) rather than an
# independent checkout/pull path that can replace live source.
if [[ -d "$JAEGER_INSTALL_ROOT/.git" ]]; then
  if [[ -n "$(git -C "$JAEGER_INSTALL_ROOT" status --porcelain)" ]]; then
    echo "✗ install checkout has local changes; nothing changed" >&2
    exit 1
  fi
  if [[ "$MIGRATE_LEGACY" -eq 1 ]]; then
    # Resume an interrupted clone/state-copy operation without losing that
    # recovery path to the normal installed-product updater.
    git -C "$JAEGER_INSTALL_ROOT" fetch --no-tags origin "$JAEGER_REF" --quiet
    CURRENT="$(git -C "$JAEGER_INSTALL_ROOT" rev-parse HEAD)"
    SELECTED="$(git -C "$JAEGER_INSTALL_ROOT" rev-parse --verify 'FETCH_HEAD^{commit}')"
    if [[ "$CURRENT" != "$SELECTED" ]]; then
      echo "✗ recovery checkout differs from selected ref; preserve it and select its original JAEGER_REF" >&2
      exit 1
    fi
  else
  # Older installed updaters ignored --ref. Refuse that path instead of
  # silently following its upstream branch or replacing running code.
  PYTHONPATH="$JAEGER_INSTALL_ROOT" "$PY" -B - "$JAEGER_INSTALL_ROOT" <<'PYTHON'
from pathlib import Path
import sys
try:
    from jaeger_ai.cli.verbs.update_verb import _preflight_update
except ImportError:
    raise SystemExit('Installed updater predates safe pinned updates; install into a separate location')
raise SystemExit(_preflight_update(Path(sys.argv[1])))
PYTHON
  echo "→ updating $JAEGER_INSTALL_ROOT through jaeger update"
  "$JAEGER_INSTALL_ROOT/jaeger" update --ref "$JAEGER_REF"
  exit $?
  fi
else
  if [[ -e "$JAEGER_INSTALL_ROOT" ]]; then
    echo "✗ $JAEGER_INSTALL_ROOT exists but is not a git repo — move it aside or set JAEGER_INSTALL_ROOT" >&2
    exit 1
  fi
  echo "→ cloning JaegerAI into $JAEGER_INSTALL_ROOT"
  mkdir -p "$(dirname "$JAEGER_INSTALL_ROOT")"
  git clone --no-checkout "$REPO_URL" "$JAEGER_INSTALL_ROOT" --quiet
  git -C "$JAEGER_INSTALL_ROOT" fetch --no-tags origin "$JAEGER_REF" --quiet
  COMMIT="$(git -C "$JAEGER_INSTALL_ROOT" rev-parse --verify 'FETCH_HEAD^{commit}')"
  git -C "$JAEGER_INSTALL_ROOT" checkout --detach "$COMMIT" --quiet
  echo "  selected revision: $COMMIT"
fi

# Carry the complete operator-state root into the correctly named install.
# This includes every agent instance, memory database, settings, credentials,
# and the active-instance selector. The source remains intact for rollback.
if [[ "$MIGRATE_LEGACY" -eq 1 ]]; then
  echo "→ migrating Jaeger AI state from $LEGACY_JAEGER_HOME"
  mkdir -p "$(dirname "$JAEGER_STATE_DEST")"
  STATE_STAGE="$(mktemp -d "$(dirname "$JAEGER_STATE_DEST")/.jaeger-state-migration.XXXXXX")"
  trap '[[ -z "${STATE_STAGE:-}" ]] || rm -rf -- "$STATE_STAGE"' EXIT
  if command -v ditto >/dev/null 2>&1; then
    ditto "$LEGACY_JAEGER_HOME/.jaeger_os" "$STATE_STAGE/state"
  else
    mkdir -p "$STATE_STAGE/state"
    cp -a "$LEGACY_JAEGER_HOME/.jaeger_os/." "$STATE_STAGE/state/"
  fi
  printf '%s\n' "$LEGACY_JAEGER_HOME" \
    > "$STATE_STAGE/state/.migrated-from"
  mv "$STATE_STAGE/state" "$JAEGER_STATE_DEST"
  rmdir "$STATE_STAGE"
  STATE_STAGE=""
  echo "  ✓ instances and settings copied; legacy install retained for rollback"
fi

# 3. Run the in-repo installer (.venv + deps incl. the git-resolved
#    jaeger-os/jaeger-kokoro-tts/jaeger-whisper-stt stack + app build +
#    ~/.jaeger/ scaffold). --product tells it this is an end-user
#    install (build the release app, not the dev shell) — every clone
#    has a dev/ tree now (0.9 split), so that can no longer be the
#    dev-vs-product signal on its own.
echo "→ running local installer..."
bash "$JAEGER_INSTALL_ROOT/install.sh" --product "$@"

cat <<EOF

╔══════════════════════════════════════════════╗
║  ✓ JaegerAI installed at $JAEGER_INSTALL_ROOT
╚══════════════════════════════════════════════╝

Instance state lives under ~/.jaeger/ (configurable via JAEGER_STATE_DIR);
the code stays writable in place (editable install — the agent self-modifies
its own skills).

Next steps:
  cd $JAEGER_INSTALL_ROOT
  ./jaeger agent create    # create your first agent
  ./jaeger                 # run it   (--tui for terminal)
  ./jaeger doctor          # environment + readiness check

Upgrade later:
  curl -fsSL $RAW_URL | JAEGER_INSTALL_ROOT=$JAEGER_INSTALL_ROOT JAEGER_REF=$JAEGER_REF bash

EOF

if [[ "$MIGRATE_LEGACY" -eq 1 ]]; then
  cat <<EOF
Migration complete:
  New app:       $JAEGER_INSTALL_ROOT
  Rollback copy: $LEGACY_JAEGER_HOME

Launch Jaeger AI and confirm your agents, memory, and settings. Only then may
you remove the old folder; the installer deliberately does not delete it.

EOF
fi
