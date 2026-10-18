#!/usr/bin/env bash
# Loopback Gateway smoke test.
#
#   scripts/smoke-gateway.sh [URL] [CALLER]
#     URL     default http://127.0.0.1:33418
#     CALLER  default ide (any caller_auth.CALLERS name)
#
# Checks: loopback-only listener, /health 200, /v1/models 401 without a token,
# 200 with the caller token, and a streamed "say ok" chat that ends in [DONE].
# The token is read through the repo's caller_auth (Keychain, or
# JAEGER_CALLER_TOKEN_DIR when set), written straight to a mode-600 header
# file, and never printed or passed in argv. Exits non-zero on any failure.
set -euo pipefail

url="${1:-http://127.0.0.1:33418}"; url="${url%/}"
caller="${2:-ide}"
model="${JAEGER_SMOKE_MODEL:-jaeger}"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
python_exe="${JAEGER_SMOKE_PYTHON:-${JAEGER_VENV:-$HOME/.jaeger/venv}/bin/python}"

fail=0
pass() { printf 'PASS  %s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*"; fail=1; }

work="$(mktemp -d "${TMPDIR:-/tmp}/jaeger-smoke.XXXXXX")"
chmod 700 "$work"
trap 'rm -rf "$work"' EXIT

hostport="${url#*://}"; hostport="${hostport%%/*}"
host="${hostport%:*}"; port="${hostport##*:}"
case "$host" in
  127.0.0.1|localhost|\[::1\]) ;;
  *) bad "URL host $host is not loopback"; exit 1 ;;
esac

# 1. Listener is loopback-only.
listen="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sort -u || true)"
if [[ -z "$listen" ]]; then
  bad "nothing listening on port $port"; exit 1
elif grep -qvE '^(127\.0\.0\.1|\[::1\]):' <<<"$listen"; then
  bad "port $port has a non-loopback listener: $(tr '\n' ' ' <<<"$listen")"
else
  pass "listener loopback-only: $(tr '\n' ' ' <<<"$listen")"
fi

code() { curl -sS -m "${2:-10}" -o "$work/body" -w '%{http_code}' "${@:3}" "$1" || echo 000; }

# 2. /health
c="$(code "$url/health")"
[[ "$c" == 200 ]] && pass "/health 200" || bad "/health $c"

# 3. No token must be refused.
c="$(code "$url/v1/models")"
[[ "$c" == 401 ]] && pass "/v1/models without token 401" || bad "/v1/models without token $c (want 401)"

# 4. Caller token -> header file (mode 600). Never echoed, never in argv.
hdr="$work/auth.hdr"
( umask 077
  PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1 \
  "$python_exe" -c '
import sys
from jaeger_ai.core.gateway.caller_auth import read_token
tok = read_token(sys.argv[1])
if not tok:
    sys.exit("no token for caller " + sys.argv[1])
with open(sys.argv[2], "w") as fh:
    fh.write("Authorization: Bearer " + tok + "\n")
' "$caller" "$hdr" ) || { bad "could not load the $caller token via caller_auth"; exit 1; }
chmod 600 "$hdr"

c="$(code "$url/v1/models" 10 -H "@$hdr")"
if [[ "$c" == 200 ]]; then
  ids="$("$python_exe" -c 'import json,sys; print(", ".join(m.get("id","?") for m in json.load(open(sys.argv[1])).get("data",[]))[:200])' "$work/body" 2>/dev/null || true)"
  pass "/v1/models with $caller token 200 ($ids)"
else
  bad "/v1/models with $caller token $c"
fi

# 5. Streamed "say ok".
start=$(date +%s)
curl -sS -N -m "${JAEGER_SMOKE_TIMEOUT:-180}" -H "@$hdr" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$model\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}]}" \
  "$url/v1/chat/completions" > "$work/stream" 2>"$work/stream.err" || true
secs=$(( $(date +%s) - start ))
summary="$("$python_exe" - "$work/stream" <<'PY'
import json, sys
text, chunks, done, err = "", 0, False, None
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line.startswith("data:"):
        continue
    data = line[5:].strip()
    if data == "[DONE]":
        done = True
        continue
    try:
        obj = json.loads(data)
    except ValueError:
        continue
    chunks += 1
    if "error" in obj:
        err = str(obj["error"].get("message", obj["error"]))[:160]
    for ch in obj.get("choices", []):
        text += (ch.get("delta") or {}).get("content") or ""
print(f"{int(done)}|{int(err is None)}|chunks={chunks} text={text.strip()[:80]!r}" + (f" error={err!r}" if err else ""))
PY
)"
IFS='|' read -r sdone sok sdesc <<<"$summary"
if [[ "$sdone" == 1 && "$sok" == 1 && "$sdesc" != *"chunks=0"* ]]; then
  pass "stream 'say ok' -> [DONE] in ${secs}s: $sdesc"
else
  bad "stream 'say ok' (${secs}s, done=$sdone): $sdesc"
fi

if [[ $fail -ne 0 ]]; then echo "SMOKE FAILED ($url)"; exit 1; fi
echo "SMOKE OK ($url, caller $caller)"
