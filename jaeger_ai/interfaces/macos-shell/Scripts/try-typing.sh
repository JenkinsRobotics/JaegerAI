#!/bin/zsh
# try-typing.sh [--check] — Matthew's own typing test of the dev shell, chat only, on the ISOLATED fba6cea9 stack
# (gateway 43438, token proxy 18801, UI 18800, its own state dir; never 33418/43418/43428, never ~/.jaeger).
# The app runs with JAEGER_SHELL_NO_LEASE=1 (no lifecycle lease) and is stopped, with the servers, on any exit
# (app quit, Ctrl-C, error). Only [key] and [shell][lease] lines are shown; any "lease ... acquired" aborts.
# --check: everything except showing the window (build, servers, health, a headless no-lease proof), then cleanup.
set -u; cd "${0:A:h}/.."
CHECK=0; [[ ${1:-} == --check ]] && CHECK=1
SHA=fba6cea9; GW="$PWD/.build/gw-$SHA"; ST="$HOME/.cache/jaeger/gw417-test-state"
APP=.build/ui-rebuild/JaegerShell.app/Contents/MacOS/JaegerShell
LOG=/tmp/jaeger-try-typing.log; APP_PID=""
cleanup() {
  trap - EXIT
  [[ -n $APP_PID ]] && kill -0 $APP_PID 2>/dev/null && { kill $APP_PID; sleep 1; kill -0 $APP_PID 2>/dev/null && kill -9 $APP_PID; }
  Scripts/test-servers.sh stop 2>&1 | tail -3
}
trap cleanup EXIT
trap 'exit 130' INT TERM   # Ctrl-C / kill: exit, which runs cleanup once
for p in 43438 18800 18801; do lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null && { echo "port $p busy — stop it first"; trap - EXIT; exit 1; }; done
[[ -d $GW/jaeger_ai ]] || { mkdir -p "$GW" && git archive $SHA jaeger_ai | tar -x -C "$GW" || { echo "cannot archive $SHA"; exit 1; }; }
# Rebuild when stale: any shell source newer than the built binary.
if [[ ! -x $APP ]] || [[ -n $(find Sources Package.swift -newer $APP -type f 2>/dev/null | head -1) ]]; then
  echo "rebuilding the shell…"; Scripts/build-shell.sh 2>&1 | grep -E "error:|Build complete" || exit 1
fi
Scripts/build-main-screen.sh | tail -1   # rebuilds the UI only when its sources changed
UNSET=(); for v in $(env | grep -E '=0\.0\.0\.0$' | cut -d= -f1); do UNSET+=(-u $v); done
env "${UNSET[@]}" -u JAEGER_SHELL_STACK_MODE -u SNAPSHOT_LIVE JAEGER_TEST_GATEWAY_ROOT="$GW" JAEGER_TEST_STATE_DIR="$ST" \
  HERMES_WEBUI_HOST=127.0.0.1 HERMES_WEBUI_SKIP_ONBOARDING=1 Scripts/test-servers.sh start 2>&1 | tail -1
[[ $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18800/v1/agents/native%3Ajaeger/home) == 200 ]] || { echo "isolated stack not healthy"; exit 1; }
SHELL_ENV=(env "${UNSET[@]}" -u JAEGER_SHELL_STACK_MODE -u JAEGER_SHELL_LEASE JAEGER_SHELL_NO_LEASE=1
  JAEGER_SHELL_UI_URL="http://127.0.0.1:18800/?host=macos" JAEGER_SHELL_GATEWAY_URL=http://127.0.0.1:43438)
if (( CHECK )); then
  T=$(mktemp -d /tmp/jg-try-typing.XXXX)
  R=$("${SHELL_ENV[@]}" JAEGER_LIFECYCLE_LEASE=$T/lease.json $APP --verify-lease-policy 2>/dev/null)
  echo "check: $R"; rm -rf $T
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
