#!/usr/bin/env python3
"""Opt-in real Hermes Runs streaming/session probe; consumes model tokens."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
def check(base, key):
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    session = "verification-native-hermes-" + uuid.uuid4().hex
    marker = uuid.uuid4().hex[:12]
    receipts = []
    for message in (
        f"Remember code {marker}. Reply SAVED. No tools or memory writes; this is only conversation context.",
        "What exact code did I ask you to remember? Reply only with the code. No tools.",
    ):
        start = time.monotonic()
        body = {"session_id": session, "input": message}
        with urlopen(Request(base + "/v1/runs", headers=headers, data=json.dumps(body).encode()), timeout=10) as response:
            rid = json.load(response)["run_id"]
        output, events = "", []
        with urlopen(Request(base + f"/v1/runs/{rid}/events", headers=headers), timeout=60) as response:
            for line in response:
                if not line.startswith(b"data:"):
                    continue
                raw = line[5:].strip()
                if raw == b"[DONE]":
                    break
                event = json.loads(raw)
                kind = event.get("event")
                events.append(kind)
                if kind == "message.delta":
                    output += str(event.get("delta") or "")
                if kind == "approval.request":
                    raise RuntimeError("Unexpected approval: probe requested no tools; no approval granted")
        if "run.completed" not in events or any(e in events for e in ("run.failed", "run.cancelled")):
            raise RuntimeError(f"Native probe failed: {events}")
        receipts.append({"session": session, "run": rid, "seconds": round(time.monotonic()-start, 2),
                         "answer": output, "events": events})
        print(json.dumps(receipts[-1]), flush=True)
    if marker not in receipts[-1]["answer"]:
        raise RuntimeError("Native Hermes Runs did not restore its previous session context")
    return receipts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8645")
    parser.add_argument("--key-file", type=Path, default=Path.home()/".hermes/jaeger-native-api.key")
    args = parser.parse_args()
    check(args.url.rstrip("/"), args.key_file.read_text().strip())
