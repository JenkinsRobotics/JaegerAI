#!/bin/zsh
set -eu

script_dir=${0:A:h}
repo_root=${script_dir:h}
webui_root="$repo_root/vendor/hermes-webui"
python_exe="${JAEGER_WEBUI_PYTHON:-$repo_root/.venv/bin/python}"
jaeger_state_home="${JAEGER_STATE_HOME:-${HOME}/.jaeger_ai}"

if [[ ! -f "$webui_root/server.py" ]]; then
  print -u2 "Jaeger WebUI fork is missing. Run: git submodule update --init vendor/hermes-webui"
  exit 1
fi
if [[ ! -x "$python_exe" ]]; then
  print -u2 "Jaeger Python is missing at $python_exe. Run the JaegerAI installer first."
  exit 1
fi

export HERMES_HOME="${JAEGER_WEBUI_AGENT_STATE:-$jaeger_state_home/hermes-webui-agent}"
export HERMES_WEBUI_STATE_DIR="${JAEGER_WEBUI_STATE_DIR:-$jaeger_state_home/hermes-webui-state}"
export HERMES_WEBUI_HOST="${JAEGER_WEBUI_HOST:-127.0.0.1}"
export HERMES_WEBUI_PORT="${JAEGER_WEBUI_PORT:-8790}"
export HERMES_WEBUI_BOT_NAME="${JAEGER_WEBUI_BOT_NAME:-JaegerAI}"
export HERMES_WEBUI_DEFAULT_WORKSPACE="${JAEGER_WEBUI_WORKSPACE:-${HOME}/workspace}"
export HERMES_WEBUI_RUNTIME_ADAPTER=runner-local
export HERMES_WEBUI_RUNNER_BASE_URL="${JAEGER_RUNNER_BASE_URL:-http://127.0.0.1:8791}"
export HERMES_WEBUI_EXTENSION_DIR="$repo_root/jaeger_ai/assets"
export HERMES_WEBUI_EXTENSION_SCRIPT_URLS=/extensions/jaeger_webui_branding.js
export HERMES_WEBUI_FOREGROUND=1

cd "$webui_root"
exec "$python_exe" "$webui_root/server.py"
