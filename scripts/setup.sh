#!/usr/bin/env bash
# JaegerAI One-Command Reproducible Setup
# Usage:
#   ./scripts/setup.sh --profile core|business|companion|droid|full [--skip-ui] [--dry-run]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="full"
SKIP_UI=0
DRY_RUN=0
VENV_DIR="${JAEGER_VENV:-}"

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
  # The Gateway imports these lightweight adapters at startup. The portable
  # profile does not need the native MLX/Kokoro and Whisper engine packages.
  core) SELECTED+=("${BUSINESS_PKGS[@]}" jaeger-realtime jaeger-vision jaeger-embodiment-minecraft "${DROID_PKGS[@]}") ;;
  business)  SELECTED+=("${BUSINESS_PKGS[@]}") ;;
  companion) SELECTED+=("${COMPANION_PKGS[@]}") ;;
  droid)     SELECTED+=("${COMPANION_PKGS[@]}" "${DROID_PKGS[@]}") ;;
  full)      SELECTED+=("${BUSINESS_PKGS[@]}" "${COMPANION_PKGS[@]}" "${DROID_PKGS[@]}") ;;
  *)
    echo "Unknown profile: ${PROFILE} (expected core|business|companion|droid|full)" >&2
    exit 2
    ;;
esac

if [[ "${PROFILE}" == "core" ]]; then
  VENV_DIR="${VENV_DIR:-${HOME}/.jaeger/core-venv}"
  STATE_DIR="${JAEGER_STATE_DIR:-${HOME}/.jaeger/core}"
  UI_OUTPUT="${STATE_DIR}/ui"
else
  VENV_DIR="${VENV_DIR:-${HOME}/.jaeger/venv}"
  STATE_DIR="${JAEGER_STATE_DIR:-${HOME}/.jaeger}"
  UI_OUTPUT="${HOME}/.cache/jaeger/ui-rebuild-mainscreen"
fi

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
# Best-effort optional voice/speaker deps (non-fatal if platform wheel unavailable)
"${PIP}" install -q onnxruntime 2>/dev/null || true

PIP_ARGS=(install --no-deps --no-build-isolation -q)
for pkg in "${SELECTED[@]}"; do
  pkg_dir="${REPO_ROOT}/packages/${pkg}"
  if [[ -d "${pkg_dir}" ]]; then
    PIP_ARGS+=(-e "${pkg_dir}")
  fi
done
echo "[jaeger-setup] Installing ${#SELECTED[@]} standalone packages..."
"${PIP}" "${PIP_ARGS[@]}"

mkdir -p "${STATE_DIR}"

echo "[jaeger-setup] Seeding verified Day-1 starter skills into ${STATE_DIR}/skills..."
"${PY}" -B -c "from pathlib import Path; from jaeger_skills import ensure_starter_skills; r = ensure_starter_skills(Path('${STATE_DIR}') / 'skills'); print(f\"[jaeger-setup] Starter skills: {len(r['installed'])} installed, {len(r['skipped'])} existing\")"

if [[ "${PROFILE}" == "companion" || "${PROFILE}" == "droid" || "${PROFILE}" == "full" ]]; then
  MF_SRC="${REPO_ROOT}/packages/jaeger-embodiment-minecraft/src/jaeger_embodiment_minecraft/mineflayer"
  MF_RUNTIME="${STATE_DIR}/runtimes/mineflayer"
  if [[ -d "${MF_SRC}" ]] && command -v npm >/dev/null 2>&1; then
    echo "[jaeger-setup] Provisioning external Mineflayer runtime in ${MF_RUNTIME}..."
    mkdir -p "${MF_RUNTIME}"
    cp -f "${MF_SRC}/package.json" "${MF_SRC}/index.js" "${MF_RUNTIME}/"
    cp -R "${MF_SRC}/lib" "${MF_RUNTIME}/"
    (
      cd "${MF_RUNTIME}"
      if [[ ! -d node_modules/mineflayer ]]; then
        npm install --no-audit --no-fund --silent
      fi
      if [[ -d node_modules/mineflayer-collectblock && ! -f node_modules/mineflayer-collectblock/lib/index.js && -x node_modules/.bin/tsc ]]; then
        (cd node_modules/mineflayer-collectblock && ../node_modules/.bin/tsc --noEmitOnError false --skipLibCheck >/dev/null 2>&1 || true)
      fi
    )
  fi
fi

if [[ "${SKIP_UI}" -eq 0 && -d "${REPO_ROOT}/jaeger_ai/interfaces/ui" ]]; then
  echo "[jaeger-setup] Building 5-Tab Studio React 19 UI..."
  (
    cd "${REPO_ROOT}/jaeger_ai/interfaces/ui"
    if [[ ! -d node_modules ]]; then
      npm ci
    fi
  )
  JAEGER_UI_DEPENDENCIES="${REPO_ROOT}/jaeger_ai/interfaces/ui" \
    "${PY}" -B "${REPO_ROOT}/jaeger_ai/interfaces/ui/scripts/build-external.py" --output-root "${UI_OUTPUT}"
fi

echo "[jaeger-setup] Running jaeger doctor..."
JAEGER_UI_DIR="${UI_OUTPUT}/dist" "${PY}" -B "${REPO_ROOT}/scripts/doctor.py"
echo "[jaeger-setup] Done! First-run commands:"
if [[ "${PROFILE}" == "core" ]]; then
  echo "  ./jaeger core                  # Boot browser-first Core on http://127.0.0.1:8790"
else
  echo "  ./jaeger start                 # Boot Gateway (:33418) + Studio WebUI (:8790)"
fi
echo "  ./jaeger onboard               # 30-second Day-1 setup (name, hybrid models & first goal)"
echo "  ./jaeger open                  # Open Studio WebUI in your browser"
echo "  ./jaeger model routing         # Configure cloud + local hybrid model tiers"
echo "  ./jaeger channels setup        # Optional: connect Telegram, Discord, Slack, or iMessage"
