#!/usr/bin/env zsh
# test-servers.sh start|stop — isolated loopback test gateway (127.0.0.1:43428) + WebUI (127.0.0.1:18790)
# for JaegerShell checks. Never touches 43418 (Gateway/IDE test gateway), launchd, or the live stack.
# Isolated state: ~/.cache/jaeger/ui-rebuild-test-state. Onboarding skipped. Inherited 0.0.0.0 vars unset.
set -u
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
ST="$HOME/.cache/jaeger/ui-rebuild-test-state"
GW_PORT=43428; UI_PORT=18790
PIDS=/tmp/jaeger-uirebuild
listening() { lsof -nP -iTCP:$1 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; }
case "${1:-}" in
start)
  for p in $GW_PORT $UI_PORT; do listening $p && { echo "port $p busy — abort"; exit 1; }; done
  UNSET=(); for v in $(env | grep -E '=0\.0\.0\.0$' | cut -d= -f1); do UNSET+=(-u $v); done
  echo "inherited 0.0.0.0 vars unset: ${UNSET[*]:-none}"
  mkdir -p "$ST"
  # JAEGER_TEST_HEADLESS=1: no background producers (no webhook listener on 8793, no sensors).
  env "${UNSET[@]}" JAEGER_STATE_DIR="$ST" JAEGER_TEST_HEADLESS=1 PYTHONPATH="$REPO" PYTHONDONTWRITEBYTECODE=1 \
    nohup "$HOME/.jaeger/venv/bin/python" -m jaeger_ai.core.gateway.server --host 127.0.0.1 --port $GW_PORT \
    > $PIDS-gateway.log 2>&1 &
  echo $! > $PIDS-gateway.pid
  (cd "$REPO" && env "${UNSET[@]}" JAEGER_STATE_DIR="$ST" HERMES_WEBUI_HOST=127.0.0.1 HERMES_WEBUI_SKIP_ONBOARDING=1 \
    JAEGER_WEBUI_ALLOW_LAN=0 JAEGER_WEBUI_PORT=$UI_PORT JAEGER_GATEWAY_URL=http://127.0.0.1:$GW_PORT PYTHONDONTWRITEBYTECODE=1 \
    nohup zsh scripts/run-jaeger-webui.sh > $PIDS-webui.log 2>&1 &
    echo $! > $PIDS-webui.pid)
  for i in {1..45}; do listening $GW_PORT && listening $UI_PORT && break; sleep 1; done
  lsof -nP -iTCP:$GW_PORT -iTCP:$UI_PORT -sTCP:LISTEN 2>/dev/null | grep -E 'COMMAND|LISTEN'
  if lsof -nP -iTCP:$GW_PORT -iTCP:$UI_PORT -sTCP:LISTEN 2>/dev/null | grep LISTEN | grep -vqE "127\.0\.0\.1:($GW_PORT|$UI_PORT) \(LISTEN\)"; then
    echo "NON-LOOPBACK LISTENER — stopping"; "$0" stop; exit 1
  fi
  listening $GW_PORT && listening $UI_PORT || { echo "servers did not come up"; "$0" stop; exit 1; }
  echo "loopback-only: yes (gateway $GW_PORT, webui $UI_PORT)"
  ;;
stop)
  for n in webui gateway; do
    [[ -f $PIDS-$n.pid ]] && { pid=$(cat $PIDS-$n.pid); kill $pid 2>/dev/null && echo "killed $n $pid"; rm -f $PIDS-$n.pid; }
  done
  sleep 3
  for p in $GW_PORT $UI_PORT; do listening $p && echo "PORT $p STILL LISTENING" || echo "port $p free"; done
  ;;
*) echo "usage: $0 start|stop"; exit 2 ;;
esac
