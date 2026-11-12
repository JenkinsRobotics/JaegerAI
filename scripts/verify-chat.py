#!/usr/bin/env python3
"""Live chat check through the product path: browser -> WebUI :8790 -> Gateway /v1.

Creates one session, sends one turn, waits for the assistant reply and checks it
was persisted. Uses model tokens. Exit 0 on a persisted reply.

    python scripts/verify-chat.py [--url http://127.0.0.1:8790] [--label smoke]
"""
import argparse
import http.cookiejar
import json
import re
import sys
import time
import urllib.request
import uuid


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8790")
    ap.add_argument("--label", default="smoke")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args(argv)
    base = args.url.rstrip("/")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    html = opener.open(base + "/", timeout=20).read().decode("utf-8", "replace")
    m = (re.search(r'name="jaeger-csrf"\s+content="([^"]+)"', html)
         or re.search(r'content="([^"]+)"\s+name="jaeger-csrf"', html))
    token = m.group(1) if m else ""

    def call(path, body=None, method=None):
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token and (method or ("POST" if body is not None else "GET")) != "GET":
            headers["X-Hermes-CSRF-Token"] = token
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        with opener.open(request, timeout=60) as response:
            text = response.read().decode()
            return json.loads(text) if text else {}

    def assistant_reply(view):
        msgs = view.get("messages") or view.get("transcript") or (view.get("session") or {}).get("messages") or []
        replies = [m for m in msgs if isinstance(m, dict) and m.get("role") == "assistant" and (m.get("content") or m.get("text"))]
        return (replies[-1].get("content") or replies[-1].get("text")) if replies else None, msgs

    sid = str(uuid.uuid4())
    created = call("/v1/sessions", {"session_id": sid, "source": "webui", "title": f"Chat check {args.label}"})
    sid = created.get("session_id") or created.get("id") or sid
    started = time.time()
    call(f"/v1/sessions/{sid}/turns", {"text": "Reply with exactly the word: pong",
                                         "request_id": str(uuid.uuid4()), "attachment_ids": []})
    reply = None
    while time.time() - started < args.timeout and not reply:
        time.sleep(2)
        reply, _ = assistant_reply(call(f"/v1/sessions/{sid}"))
    _, msgs = assistant_reply(call(f"/v1/sessions/{sid}"))
    print(json.dumps({"session": sid, "reply": str(reply)[:120] if reply else None,
                      "persisted_messages": len(msgs), "secs": round(time.time() - started, 1)}))
    return 0 if reply and len(msgs) >= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
