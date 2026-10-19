#!/usr/bin/env bash
# scripts/verify.sh — Single-command deterministic verification for JaegerAI
# Enforces clean repository invariants, hygiene tripwires, and core unit test suites.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "=================================================="
echo "  JaegerAI Verification Pipeline"
echo "=================================================="

# 1. Enforce python environment & byte-code isolation
if [[ -d /opt/homebrew/bin ]]; then
  export PATH="/opt/homebrew/bin:${PATH}"
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"
export PYTHONPATH="${REPO_ROOT}/packages/jaeger-agent:${REPO_ROOT}/packages/jaeger-os:${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
JAEGER_VENV_ROOT="${JAEGER_VENV:-${HOME}/.jaeger/venv}"
VENV_PY="${JAEGER_VENV_ROOT}/bin/python"
VENV_PYTEST="${JAEGER_VENV_ROOT}/bin/pytest"

if [[ ! -x "${VENV_PY}" || ! -x "${VENV_PYTEST}" ]]; then
  echo "[-] ERROR: Virtual environment not found at ${JAEGER_VENV_ROOT}."
  echo "    Please run ./install.sh first."
  exit 1
fi

TARGET="${1:-all}"

run_git() {
  echo "[git] Checking Git repository tracking invariants..."
  TRACKED_VIOLATIONS=$(git ls-files | grep -E '(__pycache__|\.pytest_cache|\.venv|jaeger_ai/vendor|hermes_state\.py)' || true)
  if [[ -n "${TRACKED_VIOLATIONS}" ]]; then
    echo "[-] ERROR: Forbidden paths tracked in git index:"
    echo "${TRACKED_VIOLATIONS}"
    return 1
  fi
  echo "[+] Git tracking is pristine."
}

run_hygiene() {
  echo "[hygiene] Running CI hygiene tripwires (root allowlist, features READMEs, zero in-repo state)..."
  "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_ci_hygiene.py -q --no-header
  echo "[+] CI hygiene tripwires passed."
}

run_frontend() {
  echo "=================================================="
  echo "  [TIER 1: FRONT END] Interfaces & Presentation"
  echo "=================================================="
  echo "[front-end:ide] Running IDE interface & webview unit tests..."
  IDE_OUTPUT=$(node --test jaeger_ai/interfaces/ide/tests/*.test.js 2>&1)
  PASSED_COUNT=$(echo "${IDE_OUTPUT}" | grep -E '^(ℹ|#) pass ' | awk '{print $3}')
  echo "[+] IDE interface tests passed (${PASSED_COUNT} passed)."
  echo "[front-end:webui] Running WebUI backend packaging and canonical UI routing tests..."
  "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/features/test_webui_packaging_contract.py dev/tests/jaeger_ai/features/webui/test_ui_shell_serving.py dev/tests/jaeger_ai/features/test_no_legacy_frontends.py -q --no-header
  echo "[+] WebUI front-end asset tests passed."
}

run_backend() {
  echo "=================================================="
  echo "  [TIER 2: BACK END] Core Gateway, Engine & Skills"
  echo "=================================================="
  echo "[back-end:gateway] Running Gateway durability, SQLite sessions & event store..."
  "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_gateway_durability.py -q --no-header
  echo "[+] Gateway session durability tests passed."
  echo "[back-end:tiers] Running 3-Tier Interaction Contract (Chat, Agent, Jaeger)..."
  "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_interaction_tiers.py -q --no-header
  echo "[+] Tier contract tests passed."
  echo "[back-end:skills] Running Skill Catalog and Tool Registry audit..."
  "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_skill_catalog_audit.py -q --no-header
  echo "[+] Skill Catalog audit passed."
}

run_wiring() {
  echo "=================================================="
  echo "  [TIER 3: WIRING] Integration & Wire Contracts"
  echo "=================================================="
  echo "[wiring:ide-gateway] Testing IDE client REST + SSE wire contract with Gateway..."
  "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_ide_gateway_client.py -q --no-header
  echo "[+] IDE-to-Gateway wiring contract passed."
  echo "[wiring:webui-gateway] Testing WebUI proxy wire contract with Gateway..."
  "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/interfaces/test_webui_gateway_proxy.py -q --no-header
  echo "[+] WebUI-to-Gateway wiring contract passed."
}

case "${TARGET}" in
  frontend|front-end|ui)
    run_frontend
    ;;
  backend|back-end|core)
    run_backend
    ;;
  wiring|integration|wire)
    run_wiring
    ;;
  git)
    run_git
    ;;
  hygiene)
    run_hygiene
    ;;
  ide)
    echo "[ide] Running IDE interface unit tests..."
    IDE_OUTPUT=$(node --test jaeger_ai/interfaces/ide/tests/*.test.js 2>&1)
    PASSED_COUNT=$(echo "${IDE_OUTPUT}" | grep -E '^(ℹ|#) pass ' | awk '{print $3}')
    echo "[+] IDE interface tests passed (${PASSED_COUNT} passed)."
    ;;
  gateway)
    "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_gateway_durability.py dev/tests/jaeger_ai/core/test_interaction_tiers.py -q --no-header
    ;;
  skills)
    "${VENV_PY}" -B "${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_skill_catalog_audit.py -q --no-header
    ;;
  all)
    run_git
    run_hygiene
    run_frontend
    run_backend
    run_wiring
    ;;
  *)
    echo "Unknown target: ${TARGET}"
    echo "Usage: ./scripts/verify.sh [frontend | backend | wiring | all | git | hygiene]"
    exit 1
    ;;
esac

echo "=================================================="
echo "  [SUCCESS] Verification passed for: ${TARGET}!"
echo "=================================================="
