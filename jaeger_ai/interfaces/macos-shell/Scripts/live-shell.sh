#!/usr/bin/env zsh
# live-shell.sh start [x,y,w,h] [--mock] | stop | status — VISIBLE dev session for live side-by-side checks
# (approved on-screen work only). Builds the main screen, starts the isolated loopback test servers
# (gateway 43438, token proxy 18801, main screen 18800; see test-servers.sh) and runs the dev-build
# JaegerShell in dev stack mode (lease + state stay in the isolated test state, never ~/.jaeger), placed at
# the given frame (top-left screen points) without writing the saved frame. stop quits that exact PID and
# stops the servers. Inherited 0.0.0.0 host vars are unset; never touches 43418/43428.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"; cd "$HERE"
REPO="$(git rev-parse --show-toplevel)"
APP=.build/ui-rebuild/JaegerShell.app/Contents/MacOS/JaegerShell
PIDF=/tmp/jaeger-live-shell.pid
case "${1:-}" in
start)
  [[ -x $APP ]] || { echo "build first: Scripts/build-shell.sh"; exit 1; }
  [[ -f $PIDF ]] && kill -0 "$(cat $PIDF)" 2>/dev/null && { echo "already running: $(cat $PIDF)"; exit 1; }
  FRAME="${2:-}"; MOCK=""; [[ "${*}" == *--mock* ]] && MOCK=--mock; [[ "$FRAME" == --mock ]] && FRAME=""
  Scripts/build-main-screen.sh $MOCK | tail -1
  Scripts/test-servers.sh start $MOCK | tail -1
  UNSET=(); for v in $(env | grep -E '=0\.0\.0\.0$' | cut -d= -f1); do UNSET+=(-u $v); done
  env "${UNSET[@]}" -u HERMES_WEBUI_HOST -u JAEGER_WEBUI_HOST HERMES_WEBUI_HOST=127.0.0.1 HERMES_WEBUI_SKIP_ONBOARDING=1 \
    JAEGER_SHELL_STACK_MODE=dev JAEGER_SHELL_DEV_ROOT="$REPO" JAEGER_SHELL_DEV_GATEWAY_PORT=43438 JAEGER_SHELL_DEV_UI_PORT=18800 \
    JAEGER_SHELL_DEV_STATE_DIR="$HOME/.cache/jaeger/ui-rebuild-test-state" ${FRAME:+JAEGER_SHELL_DEV_WINDOW_FRAME=$FRAME} \
    nohup $APP > /tmp/jaeger-live-shell.log 2>&1 &
  echo $! > $PIDF
  sleep 3; echo "shell pid $(cat $PIDF)"; grep -E "start_url|gateway=|\[stack\]" /tmp/jaeger-live-shell.log | head -4
  ;;
stop)
  if [[ -f $PIDF ]]; then P=$(cat $PIDF); kill "$P" 2>/dev/null; for i in {1..20}; do kill -0 "$P" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$P" 2>/dev/null && kill -9 "$P"; rm -f $PIDF; echo "shell $P stopped"; fi
  Scripts/test-servers.sh stop | tail -3
  ;;
status) [[ -f $PIDF ]] && ps -o pid=,comm= -p "$(cat $PIDF)"; lsof -nP -iTCP:43438 -iTCP:18800 -iTCP:18801 -sTCP:LISTEN | tail -n +2 | wc -l ;;
*) echo "usage: live-shell.sh start [x,y,w,h] [--mock] | stop | status"; exit 2 ;;
esac
