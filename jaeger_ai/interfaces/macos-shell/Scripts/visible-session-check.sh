#!/bin/zsh
# visible-session-check.sh — ONE batched VISIBLE session for the S4 + S5 checks of JaegerShell (ui-rebuild).
# Not run automatically: requires `--go`. `--steps` prints the plan only.
#   --go                         all steps
#   --go --only hotkey,speech    a subset (names: menu close pin notify link reveal login hotkey speech tts)
# Every human step is announced first in a floating on-screen panel (inside JaegerShell) and mirrored here.
# Never presses Start, quits the app at the end, restores every toggle it changed.
# Test servers: gateway 127.0.0.1:43428, WebUI 127.0.0.1:18790 (Scripts/test-servers.sh; never 43418).
set -u
HERE=${0:A:h}
APP=$HOME/.jaeger/apps/swift-build/ui-rebuild/JaegerShell.app
BIN=$APP/Contents/MacOS/JaegerShell
BID=com.jenkinsrobotics.JaegerAI.uirebuild
STATE=$HOME/.cache/jaeger/ui-rebuild-test-state
OUT=/tmp/jaeger-uirebuild-visible-check.json
LOGF=/tmp/jaeger-uirebuild-visible-check.log
REVEAL=$STATE/visible-check-reveal.txt
NAMES=(menu close pin notify link reveal login hotkey speech tts)
MAX_WAIT=2520   # 42 min; the app gives up at 40 min, each on-screen question at 5 min

steps() { cat <<'EOF'
Visible-session steps (S4 + S5), all inside ONE app launch (--only <names> runs a subset):
 0  preflight: main-repo check; app built; JaegerShell not running; ports 43428/18790 free; no URL override in
    the uirebuild defaults domain; baseline launch-at-login on/off (headless --verify-launch)
 1  start loopback test servers (test-servers.sh start; fails unless loopback-only)
 2  launch JaegerShell via `open -n` (its own TCC identity) with --visible-check + WebUI/gateway overrides;
    a floating panel says "starting" — operator clicks Begin (Cancel aborts cleanly)
 3  menu    status item, running icon, menu items, WebUI + Gateway probes "running"; operator confirms the icon
            (titles read only — "Start Jaeger stack…" is NEVER invoked)
 4  close   window close → hidden, app alive, page gets window.visibility=false; window.show restores
 5  pin     window.setPinned true → floating, then false (restored)
 6  notify  real notification; FAILS unless macOS reports authorized/provisional; operator confirms the banner
 7  link    link.open https://example.com/; operator confirms the browser opened
 8  reveal  file.reveal of ~/.cache/jaeger/ui-rebuild-test-state/visible-check-reveal.txt; operator confirms Finder
 9  login   launchAtLogin.set toggle → restore; compared as on/off (not_found and not_registered are both off)
10  hotkey  panel: "click Ready, then press ⌃⌥Space" → 20 s live countdown → event must reach the page;
            on a miss the operator says whether it was pressed (separates "swallowed" from "not pressed")
11  speech  panel instructions FIRST → mic + speech-recognition permission requested BEFORE recording →
            3-2-1 countdown → mic.start → "SPEAK NOW" 6 s countdown → mic.stop → max mic level + transcript
12  tts     tts.speak "Jaeger voice check complete." audibly → tts.done; operator confirms hearing it
13  app restores pin/login/mic/TTS, writes the report, quits itself (fallback: quit via osascript, then kill)
14  post: report summary; launch-at-login on/off == baseline; no JaegerShell process / lsappinfo entry;
    stop test servers; ports free; main-repo check
EOF
}

ONLY=""
case "${1:-}" in
  --steps) steps; exit 0 ;;
  --go)
    if [[ "${2:-}" == "--only" ]]; then
      ONLY=${3:-}; [[ -n $ONLY ]] || { echo "--only needs a comma-separated list: ${NAMES[*]}"; exit 2; }
      for n in ${(s:,:)ONLY}; do (( ${NAMES[(Ie)$n]} )) || { echo "unknown step '$n' (valid: ${NAMES[*]})"; exit 2; }; done
    elif [[ -n "${2:-}" ]]; then echo "unknown option ${2}"; exit 2; fi ;;
  *) echo "usage: $0 --steps | --go [--only name,name]   (the visible session runs only with --go)"; exit 2 ;;
esac

mainck() {
  local c h s
  c=$(git -C ~/GitHub/JaegerAI status --short | wc -l | tr -d ' ')
  h=$(git -C ~/GitHub/JaegerAI status --short | sort | shasum | cut -d' ' -f1)
  s=$(git -C ~/GitHub/JaegerAI stash list | wc -l | tr -d ' ')
  echo "MAINCHECK $c $h $s"
  [[ $c == 34 && $h == a7d6e34f736fda6dfcc948f8b70962eaa9390da8 && $s == 6 ]] || { echo "MAIN REPO CHANGED - STOP"; return 1; }
}
running() { pgrep -f "$BIN" >/dev/null || lsappinfo find bundleid=$BID 2>/dev/null | grep -q ASN; }
login_status() { "$BIN" --verify-launch 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["login_item_status"])'; }
onoff() { [[ $1 == enabled ]] && echo on || echo off; }
cleanup() {
  if running; then
    echo "cleanup: quitting JaegerShell"; osascript -e "tell application id \"$BID\" to quit" 2>/dev/null; sleep 3
    running && { pkill -f "$BIN"; sleep 1; }
  fi
  zsh $HERE/test-servers.sh stop
}

echo "== 0 preflight (steps: ${ONLY:-all})"
mainck || exit 1
[[ -x $BIN ]] || { echo "app not built: $BIN"; exit 1; }
running && { echo "JaegerShell already running - STOP"; exit 1; }
for p in 43428 18790; do lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1 && { echo "port $p busy - STOP"; exit 1; }; done
defaults read $BID 2>/dev/null | grep -Ei 'url' && { echo "URL override in defaults domain - STOP"; exit 1; }
LOGIN_BEFORE=$(login_status); echo "launch-at-login baseline: $LOGIN_BEFORE ($(onoff $LOGIN_BEFORE))"
trap cleanup EXIT INT TERM

echo "== 1 test servers"; zsh $HERE/test-servers.sh start || exit 1
mkdir -p $STATE && print "JaegerShell visible-check reveal target" > $REVEAL
rm -f $OUT $LOGF

echo "== 2 launch — follow the floating 'Jaeger visible check' panel on screen (top right)"
env -u HERMES_WEBUI_HOST open -n -a "$APP" --stdout $LOGF --stderr $LOGF \
  --env JAEGER_SHELL_VISIBLE_CHECK=1 --env JAEGER_SHELL_CHECK_OUT=$OUT --env JAEGER_SHELL_CHECK_REVEAL=$REVEAL \
  --env JAEGER_SHELL_CHECK_ONLY=$ONLY \
  --env JAEGER_SHELL_WEBUI_URL=http://127.0.0.1:18790/ --env JAEGER_SHELL_GATEWAY_URL=http://127.0.0.1:43428/ \
  --args --visible-check || exit 1
# Mirror the app's log read-only (the live file is never edited): print each new PROMPT/ANSWER/result line once.
seen=0; launched=0
for (( i = 0; i < MAX_WAIT * 2; i++ )); do
  if [[ -f $LOGF ]]; then
    total=$(wc -l < $LOGF | tr -d ' ')
    if (( total > seen )); then
      sed -n "$((seen + 1)),${total}p" $LOGF | grep -E '\[visible-check\] (PROMPT|ANSWER|PASS|FAIL|MANUAL|SKIP|done)' \
        | sed -E 's/^.*\[visible-check\] /   /; s/^   PROMPT /   >>> /'
      seen=$total
    fi
  fi
  running && launched=1
  (( launched )) && ! running && break
  (( !launched && i > 60 )) && { echo "app did not start within 30 s"; break; }
  sleep 0.5
done
running && echo "app still running after ${MAX_WAIT}s - cleanup will quit it"

echo "== 13/14 report"
if [[ -s $OUT ]]; then
  python3 - $OUT <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print("ok:", d.get("ok"), "| error:", d.get("error"), "| steps:", d.get("only"))
print("login (in app):", d.get("login_before"), "->", d.get("login_after"))
print("notification permission:", d.get("notification_permission"), "| voice permissions:", d.get("voice_permissions"))
print("transcript:", repr(d.get("transcript")))
for s in d.get("steps", []):
    mark = "MANUAL" if s["ok"] is None else ("PASS" if s["ok"] else "FAIL")
    print(f"  {mark:6} {s['step']}: {json.dumps(s['detail'], ensure_ascii=False)[:180]}")
PY
else echo "no report written"; fi
cleanup; trap - EXIT INT TERM
LOGIN_AFTER=$(login_status)
echo "launch-at-login: before=$LOGIN_BEFORE ($(onoff $LOGIN_BEFORE)) after=$LOGIN_AFTER ($(onoff $LOGIN_AFTER)) $([[ $(onoff $LOGIN_BEFORE) == $(onoff $LOGIN_AFTER) ]] && echo restored || echo 'NOT RESTORED')"
running && echo "JaegerShell STILL RUNNING" || echo "JaegerShell not running (pgrep + lsappinfo)"
rm -f $REVEAL
mainck
