#!/bin/zsh
set -eu

script_dir=${0:A:h}
repo_root=${script_dir:h}
webui_root="$repo_root/vendor/hermes-webui"
default_python="${HOME}/.jaeger/venv/bin/python"
if [[ ! -x "$default_python" && -x "$repo_root/.venv/bin/python" ]]; then
  default_python="$repo_root/.venv/bin/python"
fi
python_exe="${JAEGER_WEBUI_PYTHON:-$default_python}"
jaeger_state_home="${JAEGER_STATE_HOME:-${HOME}/.jaeger}"

if [[ ! -f "$webui_root/server.py" ]]; then
  print -u2 "Jaeger WebUI fork is missing. Run: git submodule update --init vendor/hermes-webui"
  exit 1
fi
if [[ ! -x "$python_exe" ]]; then
  print -u2 "Jaeger Python is missing at $python_exe (checked ~/.jaeger/venv and repo .venv). Run the JaegerAI installer first."
  exit 1
fi

export HERMES_HOME="${JAEGER_WEBUI_AGENT_STATE:-$jaeger_state_home/hermes-webui-agent}"
export HERMES_WEBUI_STATE_DIR="${JAEGER_WEBUI_STATE_DIR:-$jaeger_state_home/hermes-webui-state}"
export HERMES_WEBUI_HOST="${JAEGER_WEBUI_HOST:-0.0.0.0}"
export HERMES_WEBUI_PORT="${JAEGER_WEBUI_PORT:-8790}"
export HERMES_WEBUI_BOT_NAME="${JAEGER_WEBUI_BOT_NAME:-JaegerAI}"
export HERMES_WEBUI_DEFAULT_WORKSPACE="${JAEGER_WEBUI_WORKSPACE:-${HOME}/workspace}"
export HERMES_WEBUI_RUNTIME_ADAPTER=runner-local
export HERMES_WEBUI_RUNNER_BASE_URL="${JAEGER_RUNNER_BASE_URL:-http://127.0.0.1:8791}"
export HERMES_WEBUI_EXTENSION_DIR="$repo_root/jaeger_ai/assets"
export HERMES_WEBUI_EXTENSION_SCRIPT_URLS=/extensions/jaeger_webui_branding.js
export HERMES_WEBUI_FOREGROUND=1

# Profile listing/switching imports hermes_cli + agent.* from the hermes-agent checkout.
hermes_agent_src="${JAEGER_HERMES_AGENT_SRC:-${HOME}/GitHub/hermes-agent}"
if [[ -d "$hermes_agent_src" ]]; then
  export HERMES_WEBUI_AGENT_DIR="${HERMES_WEBUI_AGENT_DIR:-$hermes_agent_src}"
  export PYTHONPATH="${hermes_agent_src}${PYTHONPATH:+:$PYTHONPATH}"
fi


# Shared Hermes profiles + current-schema state.db for the :8790 vendor home.
# Leftover real profile dirs are renamed aside and replaced with a symlink.
PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" "$python_exe" -c \
  "from jaeger_ai.features.hermes_webui.profile_layout import prepare_vendor_webui_home; prepare_vendor_webui_home()"


cd "$webui_root"
exec "$python_exe" "$webui_root/server.py"
