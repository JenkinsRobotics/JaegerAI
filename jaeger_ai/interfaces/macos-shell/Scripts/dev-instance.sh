#!/usr/bin/env zsh
# dev-instance.sh — create the isolated test stack's instance (non-interactive create_instance) with the repo's
# default brain routing (docs/manifests/jaeger.toml): primary glm-5.3-flash:cloud through the local Ollama
# daemon (cloud tags ride its own subscription; no API keys or credentials here), deep-think coder
# kimi-k2.7-code:cloud, and local gemma-4-26b:latest as the ordered fallback. No small test models.
# State: ~/.cache/jaeger/ui-rebuild-test-state only (refuses ~/.jaeger). Never pulls or deletes models.
# Idempotent: keeps an instance that already has this routing; an older dev instance is recreated
# (create_instance backs the old directory up inside the isolated state).
set -eu
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
ST="$HOME/.cache/jaeger/ui-rebuild-test-state"
PRIMARY="glm-5.3-flash:cloud"; CODER="kimi-k2.7-code:cloud"; FALLBACK="gemma-4-26b:latest"
case "$ST/" in "$HOME/.jaeger/"*) echo "refusing ~/.jaeger"; exit 1 ;; esac
mkdir -p "$ST"
env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=en_US.UTF-8 JAEGER_STATE_DIR="$ST" JAEGER_CALLER_TOKEN_DIR="$ST/caller_tokens" \
  JAEGER_TEST_HEADLESS=1 PYTHONPATH="$REPO" PYTHONDONTWRITEBYTECODE=1 \
  "$HOME/.jaeger/venv/bin/python" - "$PRIMARY" "$CODER" "$FALLBACK" <<'PY'
import sys
from jaeger_ai.core.instance.schemas import Config, FallbackModel, dump_yaml, load_yaml
from jaeger_ai.core.instance.setup_wizard import create_instance
from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
primary, coder, fallback = sys.argv[1:4]
base = "http://127.0.0.1:11434/v1"
layout = InstanceLayout(root=resolve_instance_dir("jaeger"))
def routed(cfg):
    em = cfg.external_model
    return (em.enabled and em.provider == "ollama" and em.model == primary
            and [(f.provider, f.model) for f in em.fallback] == [("ollama", fallback)])
if layout.exists() and routed(load_yaml(layout.config_path, Config)):
    print("dev instance already routed:", primary, "→ fallback", fallback); sys.exit(0)
layout = create_instance(character_id="assistant", name="jaeger", display_name="Jaeger", user_name="Matthew",
                         awake_model=primary, awake_provider="ollama", asleep_model=coder,
                         permission_mode="confirm", overwrite=layout.exists())
cfg = load_yaml(layout.config_path, Config)
cfg.external_model.fallback = [FallbackModel(provider="ollama", model=fallback, base_url=base)]
dump_yaml(layout.config_path, cfg)
cfg = load_yaml(layout.config_path, Config)
em = cfg.external_model
print("dev instance:", layout.root)
print("routing: primary", f"{em.provider}/{em.model}", "| coder", cfg.deep_think.coder_model,
      "| fallback", [f"{f.provider}/{f.model}" for f in em.fallback], "| base", em.base_url)
PY
