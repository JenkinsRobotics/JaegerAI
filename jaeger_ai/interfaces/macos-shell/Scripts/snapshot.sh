#!/usr/bin/env zsh
# snapshot.sh [tag] [--snapshot-size WxH] [--snapshot-click <css selector>]… — headless light/dark screenshots of the main window against the MOCK main screen:
# builds the mock UI, starts the loopback test servers (--mock), runs JaegerShell --snapshot /tmp/jaeger-shots
# (window kept off every display, never activated), stops the servers, and mirrors the PNGs into the gitignored
# .build/shots/ (prefixed with [tag]) so they can be copied off the Mac. Prints the snapshot JSON summary.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"; cd "$HERE"
TAG="${1:-latest}"; shift $(( $# > 0 ? 1 : 0 ))   # remaining args go to JaegerShell (e.g. --snapshot-size 640x760)
APP=.build/ui-rebuild/JaegerShell.app/Contents/MacOS/JaegerShell
[[ -x $APP ]] || { echo "build first: Scripts/build-shell.sh"; exit 1; }
Scripts/build-main-screen.sh --mock | tail -1
Scripts/test-servers.sh start --mock | tail -1
rm -rf /tmp/jaeger-shots
env -u HERMES_WEBUI_HOST -u JAEGER_WEBUI_HOST JAEGER_SHELL_UI_URL='http://127.0.0.1:18800/?host=macos' \
  $APP --snapshot /tmp/jaeger-shots "$@" 2>/tmp/jaeger-snapshot.log > /tmp/jaeger-snapshot.json
rc=$?
Scripts/test-servers.sh stop | tail -3
mkdir -p .build/shots
for f in /tmp/jaeger-shots/jaeger-*.png(N); do cp "$f" ".build/shots/$TAG-${f:t}"; done
/usr/bin/python3 - <<'PY'
import json
r = json.load(open("/tmp/jaeger-snapshot.json"))
print("snapshot ok:", r["ok"], "| error:", r.get("error"), "| on any screen:", r["window_on_any_screen"], r["window_on_any_screen_at_end"], "| app active:", r["app_active"])
if r.get("clicks"): print("  clicks:", r["clicks"])
for n, s in sorted(r["shots"].items()):
    c, p = s["chrome"], s.get("page") or {}
    print(f"  {n}: {s.get('pixels')} chrome_ok={c['ok']} bg={c['background'][n]} under={c['under_page_background']} lights={c['traffic_lights'][0][:2]} band={p.get('band')} reserve={p.get('reserve')} prefers_dark={p.get('prefers_dark')} body_bg={p.get('body_background')}")
PY
ls .build/shots/$TAG-* 2>/dev/null
exit $rc
