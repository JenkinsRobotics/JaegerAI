#!/usr/bin/env python3
"""Opt-in live tool/control check. Creates a labeled session; denies any approval.

Uses model tokens. Never enables YOLO or grants persistent tool permission.
"""
import argparse
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def check(base, profile, message):
    def request(path, body=None):
        return urlopen(Request(base + path, data=json.dumps(body).encode() if body is not None else None,
            headers={"Cookie": f"hermes_profile={profile}", "Content-Type": "application/json"}), timeout=150)
    with request("/api/session/new", {"workspace": "/mnt/host/GitHub/JaegerAI", "profile": profile,
        "worktree": False, "model": "@ollama-rack:glm-5.3-flash:cloud"}) as response:
        sid = json.load(response)["session"]["session_id"]
    with request("/api/session/rename", {"session_id": sid, "title": "Verification — native tools and approval denial"}) as response:
        response.read()
    with request("/api/chat/start", {"session_id": sid, "message": message}) as response:
        stream = json.load(response)["stream_id"]
    print(json.dumps({"session": sid, "stream": stream, "profile": profile}), flush=True)
    started = time.monotonic()
    events, tools, answers, approvals = [], [], [], 0
    with request("/api/chat/stream?" + urlencode({"stream_id": stream})) as response:
        event = ""
        for raw in response:
            line = raw.decode().strip()
            if line.startswith("event:"):
                event = line[6:].strip()
            if not line.startswith("data:"):
                continue
            payload = json.loads(line[5:])
            events.append(event)
            if event == "approval":
                approvals += 1
                body = {"session_id": sid, "approval_id": payload["approval_id"], "choice": "deny"}
                token = payload.get("_gateway_mirror_token") or payload.get("mirror_token")
                if token:
                    body.update(run_id=payload["run_id"], mirror_token=token)
                with request("/api/approval/respond", body) as resolved:
                    result = json.load(resolved)
                print(json.dumps({"approval": "denied", "relay_ok": result.get("ok"),
                                  "seconds": round(time.monotonic() - started, 2)}), flush=True)
            elif event in {"tool", "tool_complete"}:
                tools.append(payload.get("name"))
                print(json.dumps({"event": event, "tool": payload.get("name"),
                                  "seconds": round(time.monotonic() - started, 2)}), flush=True)
            elif event in {"error", "apperror"}:
                raise RuntimeError(payload)
            elif event == "token":
                answers.append(payload.get("text", ""))
            elif event in {"done", "complete", "cancel"}:
                break
    print(json.dumps({"session": sid, "seconds": round(time.monotonic() - started, 2),
                      "events": sorted(set(events)), "tools": tools, "approvals_denied": approvals,
                      "answer": "".join(answers)[:1500]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", default="jaeger")
    parser.add_argument("--message", default="Read the first line of README.md in the current JaegerAI repository using a file tool and quote that line. Do not modify files or use network tools. Keep the answer short.")
    args = parser.parse_args()
    check(args.url.rstrip("/"), args.profile, args.message)
