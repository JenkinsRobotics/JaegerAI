#!/usr/bin/env bash
# Shared external output resolver; keeps all Swift build artifacts outside the repo.
set -euo pipefail
printf '%s\n' "${JAEGER_MAC_BUILD:-$HOME/.cache/jaeger/macos-shell}"
