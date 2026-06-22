#!/usr/bin/env bash
#
# JROS sandbox shim. Source this from your shell to make the in-repo
# ``sandbox/`` directory behave as a full, fully-isolated JROS
# install:
#
#   <repo>/sandbox/
#   ├── jaeger_os/        ← REAL COPY of ../jaeger_os/ (NOT a symlink)
#   └── .jaeger_os/       ← sandbox's own operator state
#       ├── instances/<name>/
#       ├── models/
#       ├── backups/
#       └── jaeger.env
#
# Why a copy, not a symlink
# -------------------------
# An agentic agent running in the sandbox might edit framework files
# (intentionally as a test, or via tool misuse). A symlink would mean
# those edits leak straight into the parent's real ``jaeger_os/`` and
# break the operator's working install. A real copy keeps them
# contained — the sandbox is the experiment, the parent stays clean.
#
# Refreshing from parent
# ----------------------
# Edits you make in the parent ``<repo>/jaeger_os/`` are NOT picked up
# automatically — the sandbox uses its own snapshot. When you want the
# parent's latest code in the sandbox:
#
#   dev/dev/scripts/dev_env.sh --refresh
#
# This rsyncs ``<repo>/jaeger_os/`` over ``sandbox/jaeger_os/``. Any
# agent edits in the sandbox to framework files are overwritten —
# they were the experiment, not the source of truth.
#
# Resetting completely
# --------------------
#   rm -rf sandbox/
#   source dev/dev/scripts/dev_env.sh
#
# That wipes operator state (instances, memory, etc.) AND the framework
# copy, then rebuilds from scratch.
#
# Usage
# -----
#   source dev/dev/scripts/dev_env.sh           # set up + export env into shell
#   ./run.sh setup jros-dev             # creates sandbox's test instance
#   ./run.sh --instance jros-dev        # launch the sandbox agent
#
# Or one-shot:
#
#   dev/dev/scripts/dev_env.sh ./run.sh         # run cmd with env set
#
# The sandbox tree is gitignored, so dev work never leaks into commits.

set -uo pipefail

_jros_repo="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
_sandbox="$_jros_repo/sandbox"
_src="$_jros_repo/jaeger_os"
_dst="$_sandbox/jaeger_os"

# Parse flags. Use a while-loop with shift so $@ ends up holding the
# command (if any) to exec after we've consumed our flags. The
# previous for-loop iterated over a snapshot of $@ and the shifts
# inside didn't strip non-flag args, which left trailing zsh-style
# inline comments (``# rsync the fix into sandbox``) in $@ and
# tripped exec with ``exec: #: not found``.
_refresh=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --refresh|-r)
            _refresh=1
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done
# zsh's ``interactive_comments`` option is off by default, so a
# trailing ``# comment`` typed at the prompt arrives here as args.
# Treat a leading-# token as the start of a comment and discard
# everything after it; otherwise exec would fail with
# ``exec: #: not found``.
if [[ $# -gt 0 && "${1:0:1}" == "#" ]]; then
    set --
fi

# Set up the sandbox structure. Idempotent — re-source is safe.
mkdir -p "$_sandbox" "$_sandbox/.jaeger_os/instances"

_need_copy=0
if [[ ! -d "$_dst" ]]; then
    _need_copy=1
elif [[ ! -e "$_dst/__init__.py" ]]; then
    # Partial copy — finish it.
    _need_copy=1
fi
if [[ "$_refresh" -eq 1 ]]; then
    _need_copy=1
fi

if [[ "$_need_copy" -eq 1 ]]; then
    # Block accidental refresh that would overwrite a live agent's edits.
    # Only fire the rsync when:
    #   - the dest doesn't exist yet (first run), OR
    #   - the caller explicitly passed --refresh.
    # The above flag tracks both; here we just do it.
    printf '[dev_env] copying %s → %s\n' "$_src" "$_dst" >&2
    if command -v rsync >/dev/null 2>&1; then
        # --delete so removed files in parent disappear from sandbox.
        # Exclude bytecode / caches so the sandbox copy stays clean.
        rsync -a --delete \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='.DS_Store' \
            "$_src/" "$_dst/"
    else
        # Fallback for systems without rsync (rare on macOS / Linux):
        # do a plain cp -R after wiping the target.
        rm -rf "$_dst"
        cp -R "$_src" "$_dst"
        find "$_dst" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
        find "$_dst" -name '*.pyc' -delete 2>/dev/null || true
    fi
fi

# Point the runtime at the sandbox. JAEGER_HOME drives
# ``install_root()`` in the python resolver. PYTHONPATH lets
# ``import jaeger_os`` find the sandbox copy.
export JAEGER_HOME="$_sandbox"
case ":${PYTHONPATH:-}:" in
    *":$_sandbox:"*) ;;
    *) export PYTHONPATH="$_sandbox${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

if [[ "${BASH_SOURCE[0]:-}" != "${0}" ]]; then
    # Sourced — leave the exports in the caller's shell.
    printf '[dev_env] JAEGER_HOME=%s\n' "$JAEGER_HOME" >&2
    printf '[dev_env] sandbox layout:\n  %s/jaeger_os    (isolated copy)\n  %s/.jaeger_os/    (operator state)\n' \
        "$_sandbox" "$_sandbox" >&2
    printf '[dev_env] refresh framework from parent:\n  dev/dev/scripts/dev_env.sh --refresh\n' >&2
else
    # Executed — run the rest of argv with the env set, OR exit
    # cleanly if --refresh was the only ask (no command to chain).
    if [[ $# -eq 0 ]]; then
        if [[ "$_refresh" -eq 1 ]]; then
            # ``dev_env.sh --refresh`` — refresh was the whole point.
            exit 0
        fi
        printf 'usage: source %s [--refresh]   (export env into your shell)\n' \
            "${BASH_SOURCE[0]:-$0}" >&2
        printf '   or: %s [--refresh] <cmd> [args…]   (run cmd with env set)\n' \
            "${BASH_SOURCE[0]:-$0}" >&2
        printf 'JAEGER_HOME would be: %s\n' "$JAEGER_HOME" >&2
        exit 64
    fi
    exec "$@"
fi
