#!/usr/bin/env bash
# JaegerAI One-Command Reproducible Setup
# Usage:
#   ./scripts/setup.sh --profile core|business|companion|droid|full [--skip-ui] [--dry-run]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="full"
SKIP_UI=0
DRY_RUN=0
VENV_DIR="${JAEGER_VENV:-${HOME}/.jaeger/venv}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="${2:-full}"
      shift 2
      ;;
    --venv)
      VENV_DIR="${2:-$VENV_DIR}"
      shift 2
      ;;
    --skip-ui)
      SKIP_UI=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--profile core|business|companion|droid|full] [--venv PATH] [--skip-ui] [--dry-run]"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1" >&2
      exit 2
      ;;
  esac
done

CORE_PKGS=(
  jaeger-contracts
  jaeger-events
  jaeger-reliability
  jaeger-models
  jaeger-authority
  jaeger-memory
  jaeger-tools
  jaeger-lsp
  jaeger-checkpoints
  jaeger-loop
  jaeger-orchestration
  jaeger-skills
  jaeger-mcp
  jaeger-macos
  jaeger-cognition
  jaeger-avatar
  jaeger-evals
  jaeger-protocols
  jaeger-gateway
)

BUSINESS_PKGS=(
  jaeger-business
  jaeger-youtube
  jaeger-channels
)

COMPANION_PKGS=(
  jaeger-kokoro-tts
  jaeger-whisper-stt
  jaeger-realtime
  jaeger-vision
  jaeger-embodiment-minecraft
)

DROID_PKGS=(
  jaeger-droid
  jaeger-hardware
)

SELECTED=("${CORE_PKGS[@]}")
case "${PROFILE}" in
  core) ;;
  business)  SELECTED+=("${BUSINESS_PKGS[@]}") ;;
  companion) SELECTED+=("${COMPANION_PKGS[@]}") ;;
  droid)     SELECTED+=("${COMPANION_PKGS[@]}" "${DROID_PKGS[@]}") ;;
  full)      SELECTED+=("${BUSINESS_PKGS[@]}" "${COMPANION_PKGS[@]}" "${DROID_PKGS[@]}") ;;
  *)
    echo "Unknown profile: ${PROFILE} (expected core|business|companion|droid|full)" >&2
    exit 2
    ;;
esac

echo "[jaeger-setup] Repo:    ${REPO_ROOT}"
echo "[jaeger-setup] Profile: ${PROFILE} (${#SELECTED[@]} modular packages)"
echo "[jaeger-setup] Venv:    ${VENV_DIR}"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  printf '[jaeger-setup] Would install: %s\n' "${SELECTED[*]}"
  exit 0
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "[jaeger-setup] Creating virtual environment at ${VENV_DIR}..."
  python3 -m venv "${VENV_DIR}"
fi

PIP="${VENV_DIR}/bin/pip"
PY="${VENV_DIR}/bin/python"

echo "[jaeger-setup] Ensuring base runtime dependencies..."
"${PIP}" install -q aiohttp httpx pydantic pyyaml mcp

PIP_ARGS=(install --no-deps --no-build-isolation -q)
for pkg in "${SELECTED[@]}"; do
  pkg_dir="${REPO_ROOT}/packages/${pkg}"
  if [[ -d "${pkg_dir}" ]]; then
    PIP_ARGS+=(-e "${pkg_dir}")
  fi
done
echo "[jaeger-setup] Installing ${#SELECTED[@]} standalone packages..."
"${PIP}" "${PIP_ARGS[@]}"

if [[ "${SKIP_UI}" -eq 0 && -d "${REPO_ROOT}/jaeger_ai/interfaces/ui" ]]; then
  echo "[jaeger-setup] Building 5-Tab Studio React 19 UI..."
  (
    cd "${REPO_ROOT}/jaeger_ai/interfaces/ui"
    if [[ ! -d node_modules ]]; then
      npm ci
    fi
  )
  JAEGER_UI_DEPENDENCIES="${REPO_ROOT}/jaeger_ai/interfaces/ui" \
    "${PY}" -B "${REPO_ROOT}/jaeger_ai/interfaces/ui/scripts/build-external.py"
fi

echo "[jaeger-setup] Running jaeger doctor..."
"${PY}" -B "${REPO_ROOT}/scripts/doctor.py"
echo "[jaeger-setup] Done! Start the Gateway with:"
echo "  ${PY} -m jaeger_gateway"
