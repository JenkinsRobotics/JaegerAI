#!/bin/zsh
set -eu

script_dir=${0:A:h}
repo_root=${script_dir:h}
webui_root="$repo_root/jaeger_ai/features/webui"
# The environment lives outside the checkout (AGENTS.md §1).
default_python="${JAEGER_VENV:-${HOME}/.jaeger/venv}/bin/python"
python_exe="${JAEGER_WEBUI_PYTHON:-$default_python}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${HOME}/.cache/jaeger/pycache"

if [[ ! -f "$webui_root/server.py" ]]; then
  print -u2 "Jaeger WebUI server is missing from jaeger_ai/features/webui"
  exit 1
fi
if [[ ! -x "$python_exe" ]]; then
  print -u2 "Jaeger Python is missing at $python_exe. Run the JaegerAI installer first."
  exit 1
fi

# State root: the stack passes JAEGER_STATE_HOME explicitly; a direct launch
# uses the one canonical resolver, so JAEGER_STATE_DIR isolation (and the
# refusal to nest state inside a checkout) applies here too.
if [[ -n "${JAEGER_STATE_HOME:-}" ]]; then
  jaeger_state_home="$JAEGER_STATE_HOME"
else
  jaeger_state_home="$(PYTHONPATH="$repo_root" "$python_exe" -c \
    'from jaeger_ai.core.instance.instance import operator_state_root; print(operator_state_root())')" || exit 1
fi

export HERMES_HOME="${JAEGER_WEBUI_AGENT_STATE:-$jaeger_state_home/hermes-webui-agent}"
export HERMES_WEBUI_STATE_DIR="${JAEGER_WEBUI_STATE_DIR:-$jaeger_state_home/hermes-webui-state}"
export HERMES_WEBUI_HOST="${JAEGER_WEBUI_HOST:-0.0.0.0}"
export HERMES_WEBUI_PORT="${JAEGER_WEBUI_PORT:-8790}"
export HERMES_WEBUI_BOT_NAME="${JAEGER_WEBUI_BOT_NAME:-JaegerAI}"
export HERMES_WEBUI_DEFAULT_WORKSPACE="${JAEGER_WEBUI_WORKSPACE:-${HOME}/workspace}"
# One execution path: the WebUI talks to the Jaeger Gateway. The :8791 runner is
# an isolated legacy path and is wired only when JAEGER_LEGACY_PATHS is on.
case "$(printf '%s' "${JAEGER_LEGACY_PATHS:-}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    export HERMES_WEBUI_RUNTIME_ADAPTER=runner-local
    export HERMES_WEBUI_RUNNER_PROFILES=1
    export HERMES_WEBUI_RUNNER_BASE_URL="${JAEGER_RUNNER_BASE_URL:-http://127.0.0.1:8791}"
    ;;
esac
# Health uses JAEGER_GATEWAY_URL. Do not synthesize a global chat gateway
# override: named profiles own their individual native gateway addresses.
export JAEGER_GATEWAY_URL="${JAEGER_GATEWAY_URL:-http://127.0.0.1:8810}"
export JAEGER_OLLAMA_URL="${JAEGER_OLLAMA_URL:-http://127.0.0.1:11434}"
export HERMES_WEBUI_EXTENSION_DIR="$repo_root/jaeger_ai/assets"
export HERMES_WEBUI_EXTENSION_SCRIPT_URLS=/extensions/jaeger_webui_branding.js
export HERMES_WEBUI_FOREGROUND=1

# Profile listing/switching imports hermes_cli + agent.* from the vendored
# Hermes agent (jaeger_ai/vendor/hermes_agent), which the WebUI discovers on
# its own. A separate Hermes checkout is used only when named explicitly —
# never picked up just because ~/GitHub/hermes-agent happens to exist, which
# made the WebUI's behaviour depend on the machine it ran on.
hermes_agent_src="${JAEGER_HERMES_AGENT_SRC:-}"
if [[ -n "$hermes_agent_src" && -d "$hermes_agent_src" ]]; then
  export HERMES_WEBUI_AGENT_DIR="${HERMES_WEBUI_AGENT_DIR:-$hermes_agent_src}"
  export PYTHONPATH="${repo_root}:${hermes_agent_src}${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="${repo_root}${PYTHONPATH:+:$PYTHONPATH}"
fi


# Shared Hermes profiles + current-schema state.db for the :8790 vendor home.
# Leftover real profile dirs are renamed aside and replaced with a symlink.
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$python_exe" -c \
  "import os; from pathlib import Path; from jaeger_ai.features.webui.service.profile_layout import prepare_webui_home; prepare_webui_home(Path(os.environ['HERMES_HOME']))"


# Warm the model catalogue in the background before anyone opens the page.
#
# The stock WebUI builds it lazily on first request and that build costs ~4.2s
# (measured; warm is ~0.7s). It normally lands on the operator's FIRST send,
# which reads as the UI freezing just as you hit Enter. Paying it here costs
# nothing — no one is waiting yet.
#
# Deliberately a plain HTTP call from the launcher, not a change to the WebUI:
# the browser should never pay this startup cost on its first send.
(
  for _ in $(seq 1 60); do
    if curl -fsS -m 2 -o /dev/null "http://127.0.0.1:${HERMES_WEBUI_PORT}/" 2>/dev/null; then
      curl -fsS -m 90 -o /dev/null "http://127.0.0.1:${HERMES_WEBUI_PORT}/api/models" 2>/dev/null || true
      # The release-check banner is the same shape: a ~4s network call the
      # stock UI fires on first load. Warmed here for the same reason.
      curl -fsS -m 90 -o /dev/null -X POST "http://127.0.0.1:${HERMES_WEBUI_PORT}/api/updates/check" 2>/dev/null || true
      break
    fi
    sleep 1
  done
) &

cd "$webui_root"
exec "$python_exe" "$webui_root/server.py"
