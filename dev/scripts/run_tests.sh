#!/usr/bin/env bash
#
# JROS test runner — deterministic local runs, CI-equivalent defaults.
#
# Usage:
#   dev/scripts/run_tests.sh                 # fast deterministic unit tests
#   dev/scripts/run_tests.sh --smoke         # the 30-second sanity check
#   dev/scripts/run_tests.sh --regression    # bug-fix pins (always runs in CI)
#   dev/scripts/run_tests.sh --integration   # cross-module / filesystem-heavy
#   dev/scripts/run_tests.sh --subprocess    # adds tests that fork real procs
#   dev/scripts/run_tests.sh --ui            # adds TUI / tray rendering tests
#   dev/scripts/run_tests.sh --slow          # adds slow daemon / IO tests
#   dev/scripts/run_tests.sh --model         # adds tests that load a real GGUF
#   dev/scripts/run_tests.sh --all           # everything, no marker filter
#   dev/scripts/run_tests.sh -- <args>       # everything after -- passes to pytest
#
# Why this exists:
#   * Pin TZ / LANG / PYTHONHASHSEED so a test that depends on local
#     env doesn't pass on your laptop and fail in CI.
#   * Unset auth env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY,
#     HF_TOKEN, ...) so no test accidentally hits a paid endpoint.
#   * Use pytest-xdist when available (parallel workers); fall back
#     to serial when not installed.
#   * Default to fast deterministic tests; opt in to heavier tiers
#     via the flags above. Markers are defined in pyproject.toml.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# ── env hygiene ────────────────────────────────────────────────────

# Deterministic time/locale so date/strftime-based tests don't drift.
export TZ="UTC"
export LANG="C.UTF-8"
export LC_ALL="C.UTF-8"
# Repeatable dict / set ordering across runs.
export PYTHONHASHSEED="0"
# Headless: don't open Terminal.app / Safari windows during tests.
export JAEGER_TEST_HEADLESS="1"
# No accidental API calls — strip every credential-shaped env var so
# a test that forgets to mock won't quietly hit a live endpoint.
# Pattern sweep: anything ending in API_KEY / TOKEN / SECRET / PASSWORD
# plus the AWS / GitHub / OAuth canonicals. The earlier hand-list
# missed e.g. ``OPENROUTER_API_KEY`` / ``COHERE_API_KEY`` / new
# providers as they appear; the glob catches them automatically.
while IFS='=' read -r name _value; do
    case "$name" in
        *_API_KEY|*_TOKEN|*_SECRET|*_PASSWORD|\
        AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|\
        GITHUB_TOKEN|GH_TOKEN|GIT_ASKPASS|\
        OPENAI_API_KEY|ANTHROPIC_API_KEY|HUGGINGFACE_TOKEN|HF_TOKEN|\
        GROQ_API_KEY|MISTRAL_API_KEY|TOGETHER_API_KEY|DEEPSEEK_API_KEY|\
        OPENROUTER_API_KEY|COHERE_API_KEY|XAI_API_KEY|GOOGLE_API_KEY|\
        GEMINI_API_KEY)
            unset "$name" 2>/dev/null || true
            ;;
    esac
done < <(env)

# ── flag parsing ───────────────────────────────────────────────────

MARKER_EXPR='not slow and not integration and not model and not ui and not subprocess'
EXPLICIT=0
EXTRA_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --smoke)        MARKER_EXPR="smoke"                              ; EXPLICIT=1 ;;
        --regression)   MARKER_EXPR="regression"                         ; EXPLICIT=1 ;;
        --integration)  MARKER_EXPR="integration"                        ; EXPLICIT=1 ;;
        --subprocess)   MARKER_EXPR="subprocess"                         ; EXPLICIT=1 ;;
        --ui)           MARKER_EXPR="ui"                                 ; EXPLICIT=1 ;;
        --slow)         MARKER_EXPR="slow"                               ; EXPLICIT=1 ;;
        --model)        MARKER_EXPR="model"                              ; EXPLICIT=1 ;;
        --all)          MARKER_EXPR=""                                   ; EXPLICIT=1 ;;
        --)             shift; EXTRA_ARGS+=("$@")                        ; break     ;;
        -h|--help)
            sed -n '3,21p' "${BASH_SOURCE[0]}" | sed 's/^# *//'
            exit 0
            ;;
        *)              EXTRA_ARGS+=("$1") ;;
    esac
    shift
done

# ── pytest invocation ──────────────────────────────────────────────

PYTEST=".venv/bin/pytest"
if [ ! -x "$PYTEST" ]; then
    PYTEST="pytest"
fi

# pytest-xdist parallel workers if installed — falls back to serial.
# ``-n auto`` uses every core; that's noisy on a dev laptop and
# exposes CI-vs-local differences (test ordering, fixture races).
# ``JROS_TEST_WORKERS`` pins the count for reproducibility; export
# it = 1 to debug a flake.
if "$PYTEST" --help 2>/dev/null | grep -q -- '-n NUMPROCESSES'; then
    XDIST_ARGS=(-n "${JROS_TEST_WORKERS:-4}")
else
    XDIST_ARGS=()
fi

CMD=("$PYTEST" -q ${XDIST_ARGS[@]+"${XDIST_ARGS[@]}"})
if [ -n "$MARKER_EXPR" ]; then
    CMD+=(-m "$MARKER_EXPR")
fi
CMD+=(${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"})

if [ "$EXPLICIT" -eq 0 ]; then
    printf '[run_tests] default tier — fast unit tests (%s)\n' \
        "$MARKER_EXPR" >&2
else
    printf '[run_tests] tier: %s\n' "${MARKER_EXPR:-ALL}" >&2
fi
printf '[run_tests] %s\n' "${CMD[*]}" >&2

exec "${CMD[@]}"
