#!/bin/zsh
# try-typing.sh [--live] [--check] — Matthew's own typing test of the dev shell, chat only, no lifecycle lease
# (JAEGER_SHELL_NO_LEASE=1; any "lease ... acquired" line aborts). Only [key] and [shell][lease] lines are shown.
#   default: the ISOLATED fba6cea9 stack (gateway 43438, token proxy 18801, UI 18800, its own state dir),
#            started here and stopped on exit.
#   --live:  the REAL Jaeger through the running 8790 WebUI only (it holds the caller token server-side). 8790's
#            "/" is the legacy WebUI, so our UI build is served on 127.0.0.1:18800 with /v1 proxied to 8790. No stack
#            start/stop, no gateway port contacted directly; on exit only our app and our UI server are stopped.
#   --check: everything except showing the window (build, servers, health, a headless no-lease proof), then cleanup.
set -u; cd "${0:A:h}/.."
CHECK=0; LIVE=0
for a in "$@"; do case $a in --check) CHECK=1 ;; --live) LIVE=1 ;; *) echo "usage: $0 [--live] [--check]"; exit 2 ;; esac; done
SHA=fba6cea9; GW="$PWD/.build/gw-$SHA"; ST="$HOME/.cache/jaeger/gw417-test-state"
APP=.build/ui-rebuild/JaegerShell.app/Contents/MacOS/JaegerShell
UI_DIR="${PWD:h}/ui"; UI_DIST="$HOME/.cache/jaeger/ui-rebuild-mainscreen/dist"
LOG=/tmp/jaeger-try-typing.log; APP_PID=""; UI_PID=""
cleanup() {
  trap - EXIT
  [[ -n $APP_PID ]] && kill -0 $APP_PID 2>/dev/null && { kill $APP_PID; sleep 1; kill -0 $APP_PID 2>/dev/null && kill -9 $APP_PID; }
  if (( LIVE )); then
    [[ -n $UI_PID ]] && kill -0 $UI_PID 2>/dev/null && kill $UI_PID
    sleep 0.5; lsof -nP -iTCP:18800 -sTCP:LISTEN >/dev/null && echo "port 18800 still busy" || echo "port 18800 free"
  else
    Scripts/test-servers.sh stop 2>&1 | tail -3
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM   # Ctrl-C / kill: exit, which runs cleanup once
PORTS=(18800); (( LIVE )) || PORTS=(43438 18800 18801)
for p in $PORTS; do lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null && { echo "port $p busy — stop it first"; trap - EXIT; exit 1; }; done
# Rebuild when stale: any shell source newer than the built binary.
if [[ ! -x $APP ]] || [[ -n $(find Sources Package.swift -newer $APP -type f 2>/dev/null | head -1) ]]; then
  echo "rebuilding the shell…"; Scripts/build-shell.sh 2>&1 | grep -E "error:|Build complete" || exit 1
fi
Scripts/build-main-screen.sh | tail -1   # rebuilds the UI only when its sources changed
UNSET=(); for v in $(env | grep -E '=0\.0\.0\.0$' | cut -d= -f1); do UNSET+=(-u $v); done
if (( LIVE )); then
  [[ $(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:8790/v1/sessions/agent-native%3Ajaeger/messages?limit=1") == 200 ]] \
    || { echo "8790 does not serve /v1/sessions/…/messages yet — not starting"; exit 1; }
  (cd "$UI_DIR" && env "${UNSET[@]}" JAEGER_WEBUI_URL=http://127.0.0.1:8790 JAEGER_UI_PROXY_TARGET=http://127.0.0.1:8790 \
    "$(command -v node)" node_modules/vite/bin/vite.js preview --outDir "$UI_DIST" --host 127.0.0.1 --port 18800 --strictPort \
    > /tmp/jaeger-try-typing-ui.log 2>&1) &
  UI_PID=$!
  for i in {1..20}; do lsof -nP -iTCP:18800 -sTCP:LISTEN >/dev/null && break; sleep 0.5; done
  UI_PID=$(lsof -nP -t -iTCP:18800 -sTCP:LISTEN | head -1)
else
  [[ -d $GW/jaeger_ai ]] || { mkdir -p "$GW" && git archive $SHA jaeger_ai | tar -x -C "$GW" || { echo "cannot archive $SHA"; exit 1; }; }
  env "${UNSET[@]}" -u JAEGER_SHELL_STACK_MODE -u SNAPSHOT_LIVE JAEGER_TEST_GATEWAY_ROOT="$GW" JAEGER_TEST_STATE_DIR="$ST" \
    HERMES_WEBUI_HOST=127.0.0.1 HERMES_WEBUI_SKIP_ONBOARDING=1 Scripts/test-servers.sh start 2>&1 | tail -1
fi
[[ $(curl -s -m 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:18800/v1/agents/native%3Ajaeger/home) == 200 ]] || { echo "chat backend not healthy"; exit 1; }
# Live: the shell's own gateway URL points at a closed loopback port (overrides must be 1024-65535, StartURL.swift),
# so the status-menu health probe never reaches a real gateway; abort if anything listens there.
GWURL=http://127.0.0.1:43438
if (( LIVE )); then
  GWURL=http://127.0.0.1:49151
  lsof -nP -iTCP:49151 -sTCP:LISTEN >/dev/null && { echo "port 49151 is in use; pick another closed port"; exit 1; }
fi
SHELL_ENV=(env "${UNSET[@]}" -u JAEGER_SHELL_STACK_MODE -u JAEGER_SHELL_LEASE JAEGER_SHELL_NO_LEASE=1
  JAEGER_SHELL_UI_URL="http://127.0.0.1:18800/?host=macos" JAEGER_SHELL_GATEWAY_URL=$GWURL)
if (( CHECK )); then
  T=$(mktemp -d /tmp/jg-try-typing.XXXX)
  R=$("${SHELL_ENV[@]}" JAEGER_LIFECYCLE_LEASE=$T/lease.json $APP --verify-lease-policy 2>/dev/null)
  echo "check: $R"; rm -rf $T
  (( LIVE )) && { echo "$R" | grep -q '127.0.0.1:49151' || { echo "CHECK FAILED: the shell's gateway URL is not the closed port"; exit 1; }; }
  echo "$R" | grep -q '"created":false' && echo "$R" | grep -q '"policy":"disabled"' && echo "CHECK OK (no window was shown)" || { echo "CHECK FAILED"; exit 1; }
  exit 0
fi
echo ">>> In the Jaeger window: click the message box, type:  Summarize what changed in the gateway this week in two sentences.  then press Return. Quit the app (⌘Q) or press Ctrl-C here when done."
"${SHELL_ENV[@]}" $APP 2>$LOG &
APP_PID=$!
tail -n +1 -F $LOG 2>/dev/null | while IFS= read -r line; do
  case $line in
    "[shell][lease]"*acquired*) echo "$line"; echo "ABORT: a lease was acquired"; kill $APP_PID 2>/dev/null; break ;;
    "[key]"*|"[shell][lease]"*) echo "$line" ;;
  esac
  kill -0 $APP_PID 2>/dev/null || break
done &
TAIL_PID=$!
wait $APP_PID 2>/dev/null
sleep 0.5; kill $TAIL_PID 2>/dev/null; pkill -P $TAIL_PID 2>/dev/null
grep -q "^\[shell\]\[lease\].*acquired" $LOG && { echo "a lease was acquired — see $LOG"; exit 1; }
exit 0
