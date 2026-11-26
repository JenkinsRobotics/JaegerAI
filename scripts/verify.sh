#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"
STANDALONE_SRC_PATHS="${REPO_ROOT}/packages/jaeger-contracts/src:${REPO_ROOT}/packages/jaeger-models/src:${REPO_ROOT}/packages/jaeger-tools/src:${REPO_ROOT}/packages/jaeger-loop/src:${REPO_ROOT}/packages/jaeger-memory/src:${REPO_ROOT}/packages/jaeger-authority/src:${REPO_ROOT}/packages/jaeger-orchestration/src:${REPO_ROOT}/packages/jaeger-reliability/src:${REPO_ROOT}/packages/jaeger-events/src:${REPO_ROOT}/packages/jaeger-gateway/src:${REPO_ROOT}/packages/jaeger-mcp/src:${REPO_ROOT}/packages/jaeger-macos/src:${REPO_ROOT}/packages/jaeger-lsp/src:${REPO_ROOT}/packages/jaeger-checkpoints/src:${REPO_ROOT}/packages/jaeger-skills/src:${REPO_ROOT}/packages/jaeger-cognition/src:${REPO_ROOT}/packages/jaeger-avatar/src"
export PYTHONPATH="${STANDALONE_SRC_PATHS}:${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

VENV_PY="${JAEGER_VENV:-${HOME}/.jaeger/venv}/bin/python"
TARGET="${1:-all}"

run_backend() {
  echo "=== [BACKEND] 17 Standalone Packages + E2E + Layering + Hygiene ==="
  "${VENV_PY}" -B -m pytest -q --no-header -p no:cacheprovider \
    packages/jaeger-contracts/tests \
    packages/jaeger-models/tests \
    packages/jaeger-tools/tests \
    packages/jaeger-loop/tests \
    packages/jaeger-memory/tests \
    packages/jaeger-authority/tests \
    packages/jaeger-orchestration/tests \
    packages/jaeger-reliability/tests \
    packages/jaeger-events/tests \
    packages/jaeger-gateway/tests \
    packages/jaeger-mcp/tests \
    packages/jaeger-macos/tests \
    packages/jaeger-lsp/tests \
    packages/jaeger-checkpoints/tests \
    packages/jaeger-skills/tests \
    packages/jaeger-cognition/tests \
    packages/jaeger-avatar/tests \
    dev/tests
}

run_frontend() {
  echo "=== [FRONTEND] 5 Standalone @jaeger/ui-* Packages + External Build ==="
  (cd "${REPO_ROOT}/jaeger_ai/interfaces/ui" && npm run test)
  JAEGER_UI_DEPENDENCIES="${REPO_ROOT}/jaeger_ai/interfaces/ui" \
    python3 "${REPO_ROOT}/jaeger_ai/interfaces/ui/scripts/build-external.py"
}

case "${TARGET}" in
  backend)  run_backend ;;
  frontend) run_frontend ;;
  all)      run_backend && run_frontend ;;
  *)        echo "Usage: $0 [all|backend|frontend]"; exit 2 ;;
esac
