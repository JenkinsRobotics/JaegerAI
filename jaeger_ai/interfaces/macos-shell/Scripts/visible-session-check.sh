#!/bin/zsh
# visible-session-check.sh — ONE batched VISIBLE session for the S4 + S5 checks of JaegerShell (ui-rebuild).
# Not run automatically: requires `--go`. `--steps` prints the plan only.
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

steps() { cat <<'EOF'
Visible-session steps (S4 + S5), all inside ONE app launch:
 0  preflight: main-repo check; app built; JaegerShell not running; ports 43428/18790 free; no URL override in
    the uirebuild defaults domain; baseline launch-at-login status (headless --verify-launch)
 1  start loopback test servers (test-servers.sh start; fails unless loopback-only)
 2  launch JaegerShell via `open -n` (its own TCC identity) with --visible-check + WebUI/gateway overrides
 3  menu-bar: status item present, running icon, menu items listed, WebUI + Gateway probes "running"
    (titles read only — "Start Jaeger stack…" is NEVER invoked)
 4  hide-on-close: window close → hidden, app alive, page gets window.visibility=false; window.show restores
 5  window.setPinned true → floating, then false (restored)
 6  notify (real; macOS may prompt for notifications)                   [operator: banner visible]
 7  link.open https://example.com/ (default browser opens)               [operator: page opened]
 8  file.reveal of ~/.cache/jaeger/ui-rebuild-test-state/visible-check-reveal.txt (Finder)
 9  launchAtLogin.set toggle → read → restore original (verified again after quit)
10  hotkey: press ⌃⌥Space within 20 s → "hotkey" event must reach the page [operator: press it]
11  mic.start dictation (macOS mic + speech-recognition prompts) → speak ~6 s → mic.stop → transcript
                                                                         [operator: allow, say "testing one two three"]
12  tts.speak "Jaeger voice check complete." audibly → tts.done         [operator: heard it]
13  app restores pin/login/mic/TTS, writes the report, quits itself (fallback: quit via osascript, then kill PID)
14  post: report summary; login status == baseline; no JaegerShell process / lsappinfo entry;
    stop test servers; ports free; main-repo check
EOF
}

case "${1:-}" in
  --steps) steps; exit 0 ;;
  --go) ;;
  *) echo "usage: $0 --steps | --go   (the visible session runs only with --go)"; exit 2 ;;
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
cleanup() {
  if running; then
    echo "cleanup: quitting JaegerShell"; osascript -e "tell application id \"$BID\" to quit" 2>/dev/null; sleep 3
    running && { pkill -f "$BIN"; sleep 1; }
  fi
  zsh $HERE/test-servers.sh stop
}

echo "== 0 preflight"; steps | sed -n 1p
mainck || exit 1
[[ -x $BIN ]] || { echo "app not built: $BIN"; exit 1; }
running && { echo "JaegerShell already running - STOP"; exit 1; }
for p in 43428 18790; do lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null && { echo "port $p busy - STOP"; exit 1; }; done
defaults read $BID 2>/dev/null | grep -Ei 'url' && { echo "URL override in defaults domain - STOP"; exit 1; }
LOGIN_BEFORE=$(login_status); echo "launch-at-login baseline: $LOGIN_BEFORE"
trap cleanup EXIT INT TERM

echo "== 1 test servers"; zsh $HERE/test-servers.sh start || exit 1
mkdir -p $STATE && print "JaegerShell visible-check reveal target" > $REVEAL
rm -f $OUT $LOGF

echo "== 2 launch (watch the screen; prompts: notifications, microphone, speech recognition)"
echo "   at step 10 press ⌃⌥Space; at step 11 allow the prompts and say 'testing one two three'"
env -u HERMES_WEBUI_HOST open -n -a "$APP" --stdout $LOGF --stderr $LOGF \
  --env JAEGER_SHELL_VISIBLE_CHECK=1 --env JAEGER_SHELL_CHECK_OUT=$OUT --env JAEGER_SHELL_CHECK_REVEAL=$REVEAL \
  --env JAEGER_SHELL_WEBUI_URL=http://127.0.0.1:18790/ --env JAEGER_SHELL_GATEWAY_URL=http://127.0.0.1:43428/ \
  --args --visible-check || exit 1
for i in {1..330}; do
  [[ -s $OUT ]] && ! running && break
  grep -q 'ACTION' $LOGF 2>/dev/null && { grep 'ACTION' $LOGF | tail -1 | sed 's/^/   >>> /'; sed -i '' 's/ACTION/action-shown/' $LOGF; }
  sleep 1
done
running && echo "app still running after the wait - cleanup will quit it"

echo "== 13/14 report"
grep '\[visible-check\]' $LOGF 2>/dev/null | sed 's/^/   /'
[[ -s $OUT ]] && python3 - $OUT <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print("ok:", d.get("ok"), "| error:", d.get("error"), "| login before/after (in app):", d.get("login_before"), "->", d.get("login_after"))
print("permissions after mic:", d.get("permissions_after_mic"))
for s in d.get("steps", []):
    mark = "MANUAL" if s["ok"] is None else ("PASS" if s["ok"] else "FAIL")
    print(f"  {mark:6} {s['step']}: {json.dumps(s['detail'])[:160]}")
PY
[[ -s $OUT ]] || echo "no report written"
cleanup; trap - EXIT INT TERM
LOGIN_AFTER=$(login_status)
echo "launch-at-login: before=$LOGIN_BEFORE after=$LOGIN_AFTER $([[ $LOGIN_BEFORE == $LOGIN_AFTER ]] && echo restored || echo 'NOT RESTORED')"
running && echo "JaegerShell STILL RUNNING" || echo "JaegerShell not running (pgrep + lsappinfo)"
rm -f $REVEAL
mainck
