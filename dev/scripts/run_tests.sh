#!/usr/bin/env bash
#
# JaegerAI test runner — deterministic local runs, CI-equivalent defaults.
#
# Usage:
#   dev/scripts/run_tests.sh                 # fast deterministic unit tests (default)
#   dev/scripts/run_tests.sh --smoke         # 30-second sanity check
#   dev/scripts/run_tests.sh --unit          # fast deterministic unit tests
#   dev/scripts/run_tests.sh --integration   # cross-module / filesystem-heavy
#   dev/scripts/run_tests.sh --production-path # kernel routing, authority, effects, lifecycle
#   dev/scripts/run_tests.sh --acceptance    # end-to-end acceptance & WebUI truth
#   dev/scripts/run_tests.sh --security      # security hardening & negative tests
#   dev/scripts/run_tests.sh --fault-injection # fault injection & resilience
#   dev/scripts/run_tests.sh --external-eval # external benchmark evaluation harness
#   dev/scripts/run_tests.sh --soak          # soak & leak verification
#   dev/scripts/run_tests.sh --full          # full suite across all tiers
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
#   * Passing a tier proves only what docs/architecture/TEST_ARCHITECTURE.md
#     says that tier proves. File lists here are the source of truth.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

# Prefer the independently installed Git when Apple Git is gated behind an
# unaccepted Xcode license. Put this checkout first so an editable install from
# another worktree cannot make package tests import stale source.
if [ -x /opt/homebrew/bin/git ]; then
    export PATH="/opt/homebrew/bin:${PATH}"
fi
export PYTHONPATH="${REPO}/packages/jaeger-agent:${REPO}/packages/jaeger-os:${REPO}${PYTHONPATH:+:${PYTHONPATH}}"

# ── env hygiene ────────────────────────────────────────────────────

# Deterministic time/locale so date/strftime-based tests don't drift.
export TZ="UTC"
export LANG="C.UTF-8"
export LC_ALL="C.UTF-8"
# Repeatable dict / set ordering across runs.
export PYTHONHASHSEED="0"
# Never write bytecode or caches into the repo tree
export PYTHONDONTWRITEBYTECODE="1"
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"
# Headless: don't open Terminal.app / Safari windows during tests.
export JAEGER_TEST_HEADLESS="1"
# Never share the operator's RUNNING agent. ``create_runtime`` tries the
# instance's ``run/bridge.sock`` BEFORE ``boot_for_tui``, so on a machine
# where ARES is up, a test that patches ``boot_for_tui`` never reaches its
# patch — it proxies real turns to the real brain, against real memory.
# ``dev/tests/conftest.py`` sets this too; it is repeated here because this
# script is the documented entry point and someone will run pytest through
# it long before they read the conftest.
export JAEGER_NO_ATTACH="1"
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
RUN_PACKAGES=1
TIER_NAME="unit"
EXTRA_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --smoke)
            MARKER_EXPR="smoke"
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="smoke"
            ;;
        --unit)
            MARKER_EXPR='not slow and not integration and not model and not ui and not subprocess'
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="unit"
            ;;
        --regression)
            MARKER_EXPR="regression"
            EXPLICIT=1
            RUN_PACKAGES=1
            TIER_NAME="regression"
            ;;
        --integration)
            MARKER_EXPR="integration"
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="integration"
            ;;
        --production-path)
            EXTRA_ARGS+=(
                "dev/tests/jaeger_ai/core/test_execution_lifecycle.py"
                "dev/tests/jaeger_ai/core/test_control_plane_consolidation.py"
                "dev/tests/jaeger_ai/core/test_runtime_truth.py"
                "dev/tests/jaeger_ai/core/test_policy_kernel.py"
                "dev/tests/jaeger_ai/core/test_architecture_boundary_purity.py"
                "dev/tests/test_upaa_production_runtime.py"
                # Real Gateway / EntityRuntime / run store / effect ledger;
                # only the model is scripted. (test_effects_verification.py and
                # test_state_ownership.py test modules nothing in production
                # imports, so they are unit tests and run under --unit.)
                "dev/tests/jaeger_ai/core/test_gateway_single_terminal.py"
                "dev/tests/jaeger_ai/core/test_owner_run_recovery.py"
                "dev/tests/jaeger_ai/core/test_turn_memory_projection.py"
                "dev/tests/jaeger_ai/core/test_deliberate_execution_prompt.py"
                "dev/tests/jaeger_ai/features/test_voice_session.py"
            )
            MARKER_EXPR=""
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="production-path"
            ;;
        --acceptance)
            EXTRA_ARGS+=("dev/tests/acceptance/")
            MARKER_EXPR=""
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="acceptance"
            ;;
        --security)
            EXTRA_ARGS+=(
                "dev/tests/jaeger_ai/core/test_security_hardening.py"
                "dev/tests/jaeger_ai/core/test_skills_guard.py"
                "dev/tests/jaeger_ai/core/test_gateway_cross_site.py"
                "dev/tests/jaeger_ai/core/test_gateway_approval_expiry.py"
                "dev/tests/jaeger_ai/interfaces/test_legacy_adapters_security.py"
                "packages/jaeger-agent/tests/security/"
            )
            MARKER_EXPR=""
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="security"
            ;;
        --fault-injection)
            EXTRA_ARGS+=("dev/tests/jaeger_ai/core/test_fault_injection_and_resilience.py")
            MARKER_EXPR=""
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="fault-injection"
            ;;
        --external-eval)
            EXTRA_ARGS+=("dev/tests/jaeger_ai/core/test_external_evaluation.py")
            MARKER_EXPR=""
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="external-eval"
            ;;
        --soak)
            EXTRA_ARGS+=("dev/tests/jaeger_ai/core/test_fault_injection_and_resilience.py" "-k" "soak")
            MARKER_EXPR=""
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="soak"
            ;;
        --full|--all)
            MARKER_EXPR=""
            EXPLICIT=1
            RUN_PACKAGES=1
            TIER_NAME="full"
            ;;
        --subprocess)
            MARKER_EXPR="subprocess"
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="subprocess"
            ;;
        --ui)
            MARKER_EXPR="ui"
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="ui"
            ;;
        --slow)
            MARKER_EXPR="slow"
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="slow"
            ;;
        --model)
            MARKER_EXPR="model"
            EXPLICIT=1
            RUN_PACKAGES=0
            TIER_NAME="model"
            ;;
        --)
            shift
            EXTRA_ARGS+=("$@")
            break
            ;;
        -h|--help)
            sed -n '3,21p' "${BASH_SOURCE[0]}" | sed 's/^# *//'
            exit 0
            ;;
        *)
            EXTRA_ARGS+=("$1")
            ;;
    esac
    shift
done

# ── pytest invocation ──────────────────────────────────────────────

PYTEST="${HOME}/.jaeger/venv/bin/pytest"
if [ ! -x "$PYTEST" ]; then
    PYTEST=".venv/bin/pytest"
fi
if [ ! -x "$PYTEST" ]; then
    PYTEST="pytest"
fi

# pytest-xdist parallel workers if installed — falls back to serial.
# ``-n auto`` uses every core; that's noisy on a dev laptop and
# exposes CI-vs-local differences (test ordering, fixture races).
# ``JaegerAI_TEST_WORKERS`` pins the count for reproducibility; export
# it = 1 to debug a flake.
if "$PYTEST" --help 2>/dev/null | grep -q -- '-n NUMPROCESSES'; then
    XDIST_ARGS=(-n "${JaegerAI_TEST_WORKERS:-4}")
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
    printf '[run_tests] tier: %s\n' "$TIER_NAME" >&2
fi
printf '[run_tests] %s\n' "${CMD[*]}" >&2

# Each tree in its OWN pytest process.
#
# They cannot share an interpreter: jaeger-os's app tests assert on process
# singletons (one boots a core, another expects "second instance refused"), and
# jaeger-agent's chdir into a temp workspace. Combined in one run they fail for
# reasons that have nothing to do with the code under test.
#
# Separate processes also mean a packages failure is visible. Before this, only
# dev/tests ran by default and one packages test had been failing unnoticed.
PACKAGE_SUITES=(
    "packages/jaeger-agent/tests"
    "packages/jaeger-os/dev/tests"
)

# `|| STATUS=$?` not a bare call: `set -e` is on, so an unguarded non-zero
# exit here would end the script before the package suites ever ran — which is
# exactly what happened, silently, the first time.
STATUS=0
"${CMD[@]}" || STATUS=$?

if [ "$RUN_PACKAGES" -eq 1 ]; then
    for suite in "${PACKAGE_SUITES[@]}"; do
        [ -d "$suite" ] || continue
        printf '[run_tests] %s\n' "$suite" >&2
        "$PYTEST" -q ${XDIST_ARGS[@]+"${XDIST_ARGS[@]}"} "$suite" || STATUS=$?
    done
fi

exit "$STATUS"
