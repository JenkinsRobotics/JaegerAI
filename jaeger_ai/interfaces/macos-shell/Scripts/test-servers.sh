#!/usr/bin/env zsh
# test-servers.sh start [--mock]|stop — isolated loopback test gateway (127.0.0.1:43438), the dev token proxy
# (127.0.0.1:18801, adds the test stack's OWN webui caller token like the WebUI does in production) and the
# NEW main screen (jaeger_ai/interfaces/ui, built by build-main-screen.sh [--mock]) served by `vite preview` on
# 127.0.0.1:18800, whose /v1 and /api go through the proxy. --mock serves the screenshot build (mock data).
# Never touches 43418/43428, launchd, the live stack or the Keychain (JAEGER_CALLER_TOKEN_DIR is isolated).
# Isolated state: ~/.cache/jaeger/ui-rebuild-test-state. Inherited 0.0.0.0 vars unset.
set -u
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
ST="$HOME/.cache/jaeger/ui-rebuild-test-state"
GW_PORT=${JAEGER_TEST_GATEWAY_PORT:-43438}; UI_PORT=18800; PX_PORT=18801
UI_DIR="$REPO/jaeger_ai/interfaces/ui"; UI_DIST="$HOME/.cache/jaeger/ui-rebuild-mainscreen/dist"
[[ "${2:-}" == "--mock" ]] && UI_DIST="$HOME/.cache/jaeger/ui-rebuild-mainscreen/dist-mock"
TOKENS="$ST/caller_tokens"
NODE="${JAEGER_SHELL_DEV_NODE:-$(command -v node || echo /opt/homebrew/bin/node)}"
PIDS=/tmp/jaeger-uirebuild
listening() { lsof -nP -iTCP:$1 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; }
case "${1:-}" in
start)
  for p in $GW_PORT $UI_PORT $PX_PORT; do listening $p && { echo "port $p busy — abort"; exit 1; }; done
  UNSET=(); for v in $(env | grep -E '=0\.0\.0\.0$' | cut -d= -f1); do UNSET+=(-u $v); done
  echo "inherited 0.0.0.0 vars unset: ${UNSET[*]:-none}"
  mkdir -p "$ST"
  # JAEGER_TEST_HEADLESS=1: no background producers (no webhook listener on 8793, no sensors).
  env "${UNSET[@]}" -u JAEGER_LIFECYCLE_LEASE JAEGER_STATE_DIR="$ST" JAEGER_CALLER_TOKEN_DIR="$TOKENS" JAEGER_TEST_HEADLESS=1 PYTHONPATH="$REPO" PYTHONDONTWRITEBYTECODE=1 \
    nohup "$HOME/.jaeger/venv/bin/python" -m jaeger_ai.core.gateway.server --host 127.0.0.1 --port $GW_PORT \
    > $PIDS-gateway.log 2>&1 &
  echo $! > $PIDS-gateway.pid
  nohup /usr/bin/python3 "$(dirname "$0")/dev-token-proxy.py" --port $PX_PORT --target http://127.0.0.1:$GW_PORT --token-dir "$TOKENS" \
    > $PIDS-proxy.log 2>&1 &
  echo $! > $PIDS-proxy.pid
  [[ -f "$UI_DIST/index.html" ]] || { echo "main screen not built — run Scripts/build-main-screen.sh"; "$0" stop; exit 1; }
  (cd "$UI_DIR" && env "${UNSET[@]}" JAEGER_WEBUI_URL=http://127.0.0.1:$PX_PORT JAEGER_UI_PROXY_TARGET=http://127.0.0.1:$PX_PORT \
    nohup "$NODE" node_modules/vite/bin/vite.js preview --outDir "$UI_DIST" --host 127.0.0.1 --port $UI_PORT --strictPort \
    > $PIDS-webui.log 2>&1 &
    echo $! > $PIDS-webui.pid)
  for i in {1..45}; do listening $GW_PORT && listening $UI_PORT && listening $PX_PORT && break; sleep 1; done
  lsof -nP -iTCP:$GW_PORT -iTCP:$UI_PORT -iTCP:$PX_PORT -sTCP:LISTEN 2>/dev/null | grep -E 'COMMAND|LISTEN'
  if lsof -nP -iTCP:$GW_PORT -iTCP:$UI_PORT -iTCP:$PX_PORT -sTCP:LISTEN 2>/dev/null | grep LISTEN | grep -vqE "127\.0\.0\.1:($GW_PORT|$UI_PORT|$PX_PORT) \(LISTEN\)"; then
    echo "NON-LOOPBACK LISTENER — stopping"; "$0" stop; exit 1
  fi
  listening $GW_PORT && listening $UI_PORT && listening $PX_PORT || { echo "servers did not come up"; "$0" stop; exit 1; }
  echo "loopback-only: yes (gateway $GW_PORT, token proxy $PX_PORT, main screen $UI_PORT from ${UI_DIST:t2})"
  ;;
stop)
  for n in webui proxy gateway; do
    [[ -f $PIDS-$n.pid ]] && { pid=$(cat $PIDS-$n.pid); kill $pid 2>/dev/null && echo "killed $n $pid"; rm -f $PIDS-$n.pid; }
  done
  sleep 3
  for p in $GW_PORT $UI_PORT $PX_PORT; do listening $p && echo "PORT $p STILL LISTENING" || echo "port $p free"; done
  ;;
*) echo "usage: $0 start|stop"; exit 2 ;;
esac
