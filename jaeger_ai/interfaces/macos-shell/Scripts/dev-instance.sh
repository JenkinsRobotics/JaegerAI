#!/usr/bin/env zsh
# dev-instance.sh [model] — create the isolated test stack's instance (non-interactive create_instance) so the
# dev gateway can answer turns. State: ~/.cache/jaeger/ui-rebuild-test-state only (refuses ~/.jaeger).
# Model: a small LOCAL Ollama model on 127.0.0.1:11434 (default qwen3:4b). Idempotent: keeps an existing instance.
set -eu
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
ST="$HOME/.cache/jaeger/ui-rebuild-test-state"
MODEL="${1:-qwen3:4b}"
case "$ST/" in "$HOME/.jaeger/"*) echo "refusing ~/.jaeger"; exit 1 ;; esac
[[ -f "$ST/instances/jaeger/config.yaml" ]] && { echo "dev instance exists: $ST/instances/jaeger"; exit 0; }
mkdir -p "$ST"
env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=en_US.UTF-8 JAEGER_STATE_DIR="$ST" JAEGER_CALLER_TOKEN_DIR="$ST/caller_tokens" \
  JAEGER_TEST_HEADLESS=1 PYTHONPATH="$REPO" PYTHONDONTWRITEBYTECODE=1 \
  "$HOME/.jaeger/venv/bin/python" -c '
import sys
from jaeger_ai.core.instance.setup_wizard import create_instance
m = sys.argv[1]
layout = create_instance(character_id="assistant", name="jaeger", display_name="Jaeger", user_name="Matthew",
                         awake_model=m, awake_provider="ollama", asleep_model=m, permission_mode="confirm")
print("dev instance created:", layout.root)
' "$MODEL"
