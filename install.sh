#!/usr/bin/env bash
# JaegerAI One-Command Installer (works both locally inside a checkout and via curl | bash).
# Usage:
#   ./install.sh [--profile core|business|companion|droid|full] [--skip-ui]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)"
if [[ ! -f "${REPO_ROOT}/scripts/setup.sh" ]]; then
  TARGET="${JAEGER_INSTALL_ROOT:-${HOME}/JaegerAI}"
  echo "[jaeger-install] Cloning JaegerAI into ${TARGET}..."
  git clone "${JAEGER_REPO_URL:-https://github.com/JenkinsRobotics/JaegerAI.git}" "${TARGET}"
  exec bash "${TARGET}/scripts/setup.sh" "$@"
fi

exec bash "${REPO_ROOT}/scripts/setup.sh" "$@"
