#!/usr/bin/env bash
# Point the ARES character at the persistent rack Paper world.
set -euo pipefail
cd "$(dirname "$0")/.."
export MC_HOST="${MC_HOST:-10.15.0.239}"
export MC_PORT="${MC_PORT:-25565}"
export MC_USERNAME="${MC_USERNAME:-ARES}"
export MC_AUTH="${MC_AUTH:-offline}"
export MC_VERSION="${MC_VERSION:-1.21.11}"
export API_PORT="${API_PORT:-3847}"
exec node bot/server.js --port "$API_PORT" --mc-host "$MC_HOST" --mc-port "$MC_PORT" --username "$MC_USERNAME" --auth "$MC_AUTH" --mc-version "$MC_VERSION"
