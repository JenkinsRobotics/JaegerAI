#!/usr/bin/env python3
"""Opt-in real WebUI smoke test. Creates clearly named sessions and uses model tokens."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import time
import urllib.parse
import urllib.request


def request(base, profile, path, payload=None):
    headers = {"Cookie": f"hermes_profile={profile}", "Content-Type": "application/json"}
    data = None if payload is None else json.dumps(payload).encode()
    return urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers), timeout=180)


def check_roundtable_answers(text, checkword, first_turn):
    """The echoed question is not evidence that any member answered it."""
    round1 = text.split("## Round 2", 1)[0]
    expected = ("Jaeger", "Hermes", "OpenClaw") if first_turn else ("Jaeger",)
    for member in expected:
        match = re.search(r"^### [^\n]*\b" + member + r"\s*\n(.*?)(?=^### |\Z)", round1, re.M | re.S)
        if not match or checkword not in match.group(1):
            raise RuntimeError(f"Roundtable: {member} did not return the expected check word")
    if re.search(r"^\[(?:Agent|Hermes|Jaeger|OpenClaw) error:", text, re.M):
        raise RuntimeError("Roundtable contains a member failure; inspect the verification session")


def verify(base, profile, model=None):
    started = time.monotonic()
    body = {"workspace": "/workspace", "profile": profile, "worktree": False}
    if model:
        body["model"] = model
    with request(base, profile, "/api/session/new", body) as response:
        session = json.load(response)["session"]["session_id"]
    checkword = f"{profile.upper()}-{session[:6]}"
    with request(base, profile, "/api/session/rename", {
        "session_id": session, "title": "Verification — provider and session continuity",
    }) as response:
        response.read()
    for number, message in enumerate([
        f"Hold the check word {checkword} in this conversation only. Reply briefly with READY and the check word. Do not use tools or save to long-term memory.",
        "What check word did I ask you to remember? Answer briefly without tools.",
    ], 1):
        if profile == "roundtable" and number == 2:
            message = "/quick @jaeger " + message
        with request(base, profile, "/api/chat/start", {"session_id": session, "message": message}) as response:
            result = json.load(response)
        stream = result.get("stream_id")
        if not stream:
            raise RuntimeError(f"{profile}: chat did not start: {result}")
        print(json.dumps({"profile": profile, "session": session, "turn": number, "started": True}), flush=True)
        events = []
        text = ""
        with request(base, profile, "/api/chat/stream?" + urllib.parse.urlencode({"stream_id": stream})) as response:
            event = ""
            for raw in response:
                line = raw.decode().strip()
                if line.startswith("event:"):
                    event = line[6:].strip()
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:])
                events.append(event)
                if event in {"error", "apperror", "cancel"}:
                    raise RuntimeError(f"{profile}: {event}: {payload}")
                if event == "token":
                    text += payload.get("text", "")
                if event in {"done", "complete"}:
                    break
        with request(base, profile, "/api/session?" + urllib.parse.urlencode({"session_id": session})) as response:
            saved = json.load(response)
        print(json.dumps({"profile": profile, "turn": number, "seconds": round(time.monotonic() - started, 1),
                          "events": sorted(set(events)), "text": text[:180],
                          "remembered": checkword in text,
                          "saved": bool(saved)}), flush=True)
        if checkword not in text:
            raise RuntimeError(f"{profile}: missing expected answer, inspect session {session}")
        if profile == "roundtable":
            check_roundtable_answers(text, checkword, first_turn=number == 1)
        if profile != "roundtable" and "Round 1 — Everyone Answers" in text:
            raise RuntimeError(f"{profile}: misrouted to Roundtable")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", help="Optional model override; otherwise preserve each profile's default")
    parser.add_argument("--profiles", nargs="+", default=["default", "jaeger", "openclaw", "roundtable"])
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=len(args.profiles)) as pool:
        list(pool.map(lambda profile: verify(args.url, profile, args.model), args.profiles))
