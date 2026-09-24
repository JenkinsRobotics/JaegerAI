#!/usr/bin/env python3
"""Drive one real turn through a Jaeger Gateway exactly as the IDE does, and report it.

    gateway_turn.py --gateway http://127.0.0.1:18810 --workspace /tmp/work "fix the tests"

Creates a session, admits the turn, follows the SSE stream to a terminal event and
prints the ordered tool activity, plans, and final answer. ``--auto-approve`` answers
tool approvals — use it only against a scratch Gateway, never a live one.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid


def call(base, method, path, body=None, timeout=30):
    req = urllib.request.Request(
        base + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"null")


def stream(base, session_id, deadline):
    req = urllib.request.Request(f"{base}/v1/sessions/{session_id}/stream?last_event_id=0",
                                 headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=max(5, deadline - time.time())) as resp:
        name, data = "message", []
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line == "":
                if data:
                    yield name, json.loads("\n".join(data))
                name, data = "message", []
            elif line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
            if time.time() > deadline:
                return


def run_turn(gateway, prompt, workspace, *, model="", provider="", timeout=600, auto_approve=False):
    """One admitted turn, followed to its terminal event. Returns the summary dict."""
    sid = uuid.uuid4().hex
    call(gateway, "POST", "/v1/sessions",
         {"session_id": sid, "title": "gateway_turn", "workspace": workspace, "source": "ide"})
    rid = uuid.uuid4().hex
    body = {"text": prompt, "request_id": rid}
    if model:
        body["model"] = model
        if provider:
            body["provider"] = provider
    started = time.time()
    call(gateway, "POST", f"/v1/sessions/{sid}/turns", body)

    tools, plans, terminal, approvals, answer = [], [], None, 0, ""
    deadline = started + timeout
    for name, frame in stream(gateway, sid, deadline):
        # An SSE frame is an envelope: {event_id, event, data: {...payload...}}.
        data = frame.get("data") if isinstance(frame.get("data"), dict) else frame
        name = frame.get("event") or name
        if data.get("request_id") not in (None, rid):
            continue
        if name == "tool.started":
            tools.append(data.get("tool"))
        elif name == "turn.plan":
            plans.append([(s["status"][0], s["step"]) for s in data["plan"]])
        elif name == "approval.request":
            approvals += 1
            if auto_approve:
                call(gateway, "POST", f"/v1/approvals/{data['approval_id']}",
                     {"approved": True, "decision": "once"})
        elif name in ("turn.finish", "turn.failed", "turn.cancelled", "turn.unknown"):
            terminal = name
            answer = str(data.get("text") or data.get("error") or "")
            break
    receipt = call(gateway, "GET", f"/v1/sessions/{sid}/requests/{rid}")
    if terminal == "turn.finish":
        # The final answer is the session's last assistant message (persisted
        # before turn.finish), not a field of the finish event.
        messages = call(gateway, "GET", f"/v1/sessions/{sid}").get("messages", [])
        answer = next((m["content"] for m in reversed(messages) if m.get("role") == "assistant"), "")
    return {"session": sid, "request": rid, "terminal": terminal, "status": receipt.get("status"),
            "seconds": round(time.time() - started, 1), "tools": tools, "plans": plans,
            "approvals": approvals, "answer": answer[:1500]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--gateway", default="http://127.0.0.1:18810")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--provider", default="")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--auto-approve", action="store_true")
    ap.add_argument("--json", action="store_true", help="print one JSON summary line")
    args = ap.parse_args()
    summary = run_turn(args.gateway, args.prompt, args.workspace, model=args.model,
                       provider=args.provider, timeout=args.timeout, auto_approve=args.auto_approve)
    print(json.dumps(summary) if args.json else json.dumps(summary, indent=2))
    return 0 if summary["terminal"] == "turn.finish" else 1


if __name__ == "__main__":
    sys.exit(main())
