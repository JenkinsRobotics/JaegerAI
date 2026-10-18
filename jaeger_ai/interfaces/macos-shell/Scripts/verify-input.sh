#!/bin/zsh
# Headless input proof: real NSEvents (NSWindow.sendEvent) into the offscreen shell (mock build). Asserts that
# Return posts a turn, a Stop click stops it, a Send click posts a turn, and menus are exclusive and close on outside click and Escape.
# Exit 0 only if all pass. Never shows a window or uses synthetic system input.
set -u; cd "${0:A:h}/.."
P='eval:JSON.stringify({user:document.querySelectorAll(".jg-bubble--user").length,val:document.querySelector(".jg-composer__input").value.length,stop:!!document.querySelector("[aria-label^=Stop]"),menus:[...document.querySelectorAll("[role=menu]")].map(m=>m.getAttribute("aria-label"))})'
Scripts/snapshot.sh verify-input --snapshot-click "wait:2500" --snapshot-click "$P" \
  --snapshot-click "nsclick:.jg-composer__input" --snapshot-click "type:.jg-composer__input|Hello from a real Return" \
  --snapshot-click "nskey:return" --snapshot-click "wait:800" --snapshot-click "$P" --snapshot-click "nsclick:[aria-label^=Stop]" --snapshot-click "wait:800" --snapshot-click "$P" \
  --snapshot-click "type:.jg-composer__input|Hello from a real click" --snapshot-click "nsclick:.jg-send" --snapshot-click "wait:800" --snapshot-click "$P" \
  --snapshot-click "nsclick:[aria-label^=Stop]" --snapshot-click "wait:1200" \
  --snapshot-click "nsrclick:.jg-bubble--assistant" --snapshot-click "$P" \
  --snapshot-click "nsclick:button[aria-label='Attach file']" --snapshot-click "$P" \
  --snapshot-click "nsclick:.jg-composer__input" --snapshot-click "$P" \
  --snapshot-click "nsrclick:.jg-bubble--assistant" --snapshot-click "nskey:escape" --snapshot-click "$P" >/dev/null 2>&1
python3 - <<'PY'
import json, sys
r = json.load(open("/tmp/jaeger-snapshot.json"))
s = [json.loads(c["result"]) for c in r["clicks"] if c["selector"].startswith("eval:JSON") and c.get("result")]
if len(s) != 8: print("FAIL: expected 7 probes, got", len(s)); sys.exit(1)
checks = [
  ("Return posts a turn", s[1]["user"] == s[0]["user"] + 1 and s[1]["val"] == 0 and s[1]["stop"]),
  ("Stop click stops the running turn", not s[2]["stop"]),
  ("Send click posts a turn", s[3]["user"] == s[2]["user"] + 1 and s[3]["val"] == 0),
  ("right-click opens the message menu", s[4]["menus"] == ["Message actions"]),
  ("opening + closes it (one menu at a time)", s[5]["menus"] == ["Composer actions"]),
  ("a click outside closes the menu", s[6]["menus"] == []),
  ("Escape closes the menu", s[7]["menus"] == []),
]
for name, ok in checks: print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(ok for _, ok in checks) else 1)
PY
