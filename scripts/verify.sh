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
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"
VENV_PY="${HOME}/.jaeger/venv/bin/python"
VENV_PYTEST="${HOME}/.jaeger/venv/bin/pytest"

if [[ ! -x "${VENV_PY}" ]]; then
  echo "[-] ERROR: Virtual environment not found at ${VENV_PY}."
  echo "    Please run ./install.sh first."
  exit 1
fi

echo "[1/4] Checking Git repository tracking invariants..."
# Check for forbidden tracked patterns in git
TRACKED_VIOLATIONS=$(git ls-files | grep -E '(__pycache__|\.pytest_cache|\.venv|jaeger_ai/vendor|hermes_state\.py)' || true)
if [[ -n "${TRACKED_VIOLATIONS}" ]]; then
  echo "[-] ERROR: Forbidden paths tracked in git index:"
  echo "${TRACKED_VIOLATIONS}"
  exit 1
fi
echo "[+] Git tracking is pristine."

echo "[2/4] Running CI hygiene tripwires (root allowlist, features READMEs, zero in-repo state)..."
"${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_ci_hygiene.py -q --no-header
echo "[+] CI hygiene tripwires passed."

echo "[3/4] Running IDE interface unit tests..."
IDE_OUTPUT=$(node --test jaeger_ai/interfaces/ide/tests/*.test.js 2>&1)
PASSED_COUNT=$(echo "${IDE_OUTPUT}" | grep -E '^(ℹ|#) pass ' | awk '{print $3}')
echo "[+] IDE interface tests passed (${PASSED_COUNT} passed)."

echo "[4/4] Running core Gateway client & Skill Catalog audit..."
"${VENV_PYTEST}" dev/tests/jaeger_ai/core/test_ide_gateway_client.py dev/tests/jaeger_ai/core/test_skill_catalog_audit.py -q --no-header
echo "[+] Core Gateway client & Skill Catalog audit passed."

echo "=================================================="
echo "  [SUCCESS] All verification invariants passed!"
echo "=================================================="
