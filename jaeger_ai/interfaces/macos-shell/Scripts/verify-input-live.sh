#!/bin/zsh
# verify-input.sh --live: the real UI build on the isolated fba6cea9 gateway (43438, isolated state, loopback,
# ports freed by snapshot.sh). One REAL Return (NSWindow.sendEvent) with Scripts/live-prompt.txt must post exactly
# one message: user bubbles +1, composer cleared, exactly 1 POST through the dev token proxy.
set -u; cd "${0:A:h}/.."
GW="${JAEGER_TEST_GATEWAY_ROOT:-$PWD/.build/gw-fba6cea9}"; ST="${JAEGER_TEST_STATE_DIR:-$HOME/.cache/jaeger/gw417-test-state}"
[[ -d $GW/jaeger_ai ]] || { echo "no gateway archive at $GW (git archive fba6cea9 jaeger_ai | tar -x -C $GW)"; exit 2; }
PROMPT="$(cat Scripts/live-prompt.txt)"
P='eval:JSON.stringify({user:document.querySelectorAll(".jg-bubble--user").length,val:document.querySelector(".jg-composer__input").value.length,stop:!!document.querySelector("[aria-label^=Stop]")})'
SNAPSHOT_LIVE=1 SNAPSHOT_TIMEOUT_S=90 JAEGER_TEST_GATEWAY_ROOT="$GW" JAEGER_TEST_STATE_DIR="$ST" Scripts/snapshot.sh verify-input-live \
  --snapshot-click "wait:5000" --snapshot-click "focus" --snapshot-click "$P" --snapshot-click "nsclick:.jg-composer__input" \
  --snapshot-click "type:.jg-composer__input|$PROMPT" --snapshot-click "nskey:return" --snapshot-click "wait:4000" --snapshot-click "$P" \
  > /tmp/jg-verify-input-live.log 2>&1
POSTS=$(grep -c "POST /v1/sessions/.*/turns" /tmp/jaeger-uirebuild-proxy.log)
POSTS=$POSTS python3 - <<'PY'
import json, os, sys
r = json.load(open("/tmp/jaeger-snapshot.json"))
s = [json.loads(c["result"]) for c in r["clicks"] if c["selector"].startswith("eval:JSON") and c.get("result")]
focus = next(c["result"] for c in r["clicks"] if c["selector"] == "focus"); print(focus)
posts = int(os.environ["POSTS"])
print(f"before={s[0]} after={s[1]} turn POSTs={posts}")
checks = [("one Return posts exactly one message", s[1]["user"] == s[0]["user"] + 1 and s[1]["val"] == 0 and posts == 1)]
for name, ok in checks: print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(ok for _, ok in checks) else 1)
PY
