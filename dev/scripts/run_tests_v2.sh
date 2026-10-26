#!/usr/bin/env bash
# Modern test runner — 4-tier architecture (v0.13.0)
#
# Tiers:
#   --contracts    Tool/API schema validation (< 10s)
#   --properties   Property-based invariant tests (< 30s)
#   --trajectories Scripted LLM end-to-end paths (< 60s)
#   --acceptance   Live system tests (requires Gateway)
#   (default)      contracts + properties + trajectories
#   --all          Everything including acceptance
#
# Based on 2024-2026 AI engineering research:
# - Layer isolation (deterministic infrastructure, scripted LLM)
# - Contract testing (schema validation at boundaries)
# - Property-based testing (invariants, not examples)
# - Trajectory evaluation (process, not just outcome)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

# Environment
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"
export PYTHONPATH="${REPO_ROOT}/packages/jaeger-agent:${REPO_ROOT}/packages/jaeger-os:${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Find Python
JAEGER_VENV_ROOT="${JAEGER_VENV:-${HOME}/.jaeger/venv}"
VENV_PY="${JAEGER_VENV_ROOT}/bin/python"
VENV_PYTEST="${JAEGER_VENV_ROOT}/bin/pytest"

if [[ -x "${VENV_PY}" ]]; then
    PY="${VENV_PY}"
    PYTEST="${VENV_PYTEST}"
else
    PY="python3"
    PYTEST="pytest"
fi

# Parse arguments
TIER="default"
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --contracts) TIER="contracts"; shift ;;
        --properties) TIER="properties"; shift ;;
        --trajectories) TIER="trajectories"; shift ;;
        --acceptance) TIER="acceptance"; shift ;;
        --all) TIER="all"; shift ;;
        --legacy) TIER="legacy"; shift ;;  # Old test system
        --smoke) TIER="smoke"; shift ;;
        -h|--help)
            echo "Usage: $0 [--contracts|--properties|--trajectories|--acceptance|--all|--legacy] [pytest args]"
            echo ""
            echo "Modern 4-tier testing (default):"
            echo "  --contracts    Tool/API schema validation (< 10s)"
            echo "  --properties   Property-based invariant tests (< 30s)"
            echo "  --trajectories Scripted LLM end-to-end paths (< 60s)"
            echo "  --acceptance   Live system tests (requires Gateway)"
            echo "  --all          Everything including acceptance"
            echo "  (default)      contracts + properties + trajectories"
            echo ""
            echo "Legacy options:"
            echo "  --legacy       Old 10-tier test system"
            echo "  --smoke        Quick smoke tests"
            exit 0
            ;;
        --) shift; EXTRA_ARGS+=("$@"); break ;;
        *) EXTRA_ARGS+=("$1"); shift ;;
    esac
done

echo "========================================"
echo "  JaegerAI Modern Test Runner (v0.13.0)"
echo "========================================"
echo ""

run_tests() {
    local tier="$1"
    local path="$2"
    local marker="$3"
    local extra="${4:-}"
    
    echo "→ Running ${tier} tests..."
    if [[ -d "${path}" ]]; then
        if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
            ${PYTEST} "${path}" -v ${marker} ${extra} "${EXTRA_ARGS[@]}" 2>&1 || {
                echo "❌ ${tier} tests failed"
                return 1
            }
        else
            ${PYTEST} "${path}" -v ${marker} ${extra} 2>&1 || {
                echo "❌ ${tier} tests failed"
                return 1
            }
        fi
        echo "✅ ${tier} tests passed"
    else
        echo "⚠️  No ${tier} tests found at ${path}"
    fi
    echo ""
}

case "${TIER}" in
    contracts)
        run_tests "contracts" "dev/tests/contracts/" ""
        ;;
    properties)
        run_tests "properties" "dev/tests/properties/" "not slow"
        ;;
    trajectories)
        run_tests "trajectories" "dev/tests/trajectories/" "not slow and not acceptance"
        ;;
    acceptance)
        echo "→ Running acceptance tests (requires Gateway on :33418)..."
        run_tests "acceptance" "dev/tests/acceptance/" "acceptance"
        ;;
    all)
        run_tests "contracts" "dev/tests/contracts/" ""
        run_tests "properties" "dev/tests/properties/" "not slow"
        run_tests "trajectories" "dev/tests/trajectories/" "not slow and not acceptance"
        run_tests "acceptance" "dev/tests/acceptance/" "acceptance"
        ;;
    default)
        # Fast feedback loop: contracts + properties + trajectories
        run_tests "contracts" "dev/tests/contracts/" ""
        run_tests "properties" "dev/tests/properties/" "not slow"
        run_tests "trajectories" "dev/tests/trajectories/" "not slow and not acceptance"
        ;;
    legacy)
        echo "→ Running legacy test suite..."
        if [[ -x "dev/scripts/run_tests.sh" ]]; then
            dev/scripts/run_tests.sh "${EXTRA_ARGS[@]}"
        else
            echo "❌ Legacy test runner not found"
            exit 1
        fi
        ;;
    smoke)
        echo "→ Running smoke tests..."
        ${PYTEST} dev/tests/ -m smoke -x -q "${EXTRA_ARGS[@]}"
        ;;
    *)
        echo "Unknown tier: ${TIER}"
        echo "Run $0 --help for usage"
        exit 1
        ;;
esac

echo "========================================"
echo "  Test run complete"
echo "========================================"
