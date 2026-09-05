#!/bin/zsh
# Jaeger-owned compatibility launcher for the unchanged ARES host-tool target.
# Separate management ports prevent it colliding with Jaeger's own gateway.
set -euo pipefail

export STATS_ADDR=127.0.0.1:15022
export READINESS_ADDR=127.0.0.1:15023
export ADMIN_ADDR=127.0.0.1:15002

exec "$HOME/Library/Application Support/ARES/bin/agentgateway-v1.5.0" \
  --file "$HOME/.ares/gateway/config.yaml"
