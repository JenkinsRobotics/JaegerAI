"""JaegerAI Operator CLI & Interactive Streaming Terminal Chat (TUI).

Talks directly to the standalone modular Gateway (`http://127.0.0.1:33418`) over
HTTP + SSE with zero external daemon dependencies and <100ms startup.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# Minimal ANSI styling (respects NO_COLOR)
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
_BOLD = "\033[1m" if _COLOR else ""
_DIM = "\033[2m" if _COLOR else ""
_CYAN = "\033[36m" if _COLOR else ""
_GREEN = "\033[32m" if _COLOR else ""
_YELLOW = "\033[33m" if _COLOR else ""
_RED = "\033[31m" if _COLOR else ""
_RESET = "\033[0m" if _COLOR else ""


def _gateway_url() -> str:
    host = os.environ.get("JAEGER_GATEWAY_HOST") or "127.0.0.1"
    port = os.environ.get("JAEGER_GATEWAY_PORT") or "33418"
    return f"http://{host}:{port}"


def _webui_url() -> str:
    host = os.environ.get("JAEGER_GATEWAY_HOST") or "127.0.0.1"
    port = os.environ.get("JAEGER_WEBUI_PORT") or "8790"
    return f"http://{host}:{port}"


def _api_json(method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float = 10.0) -> dict[str, Any]:
    url = _gateway_url() + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _print_status() -> int:
    try:
        health = _api_json("GET", "/health")
        res = _api_json("GET", "/v1/system/resources").get("resources") or {}
        cog = _api_json("GET", "/v1/cognition/state").get("cognition") or {}
        ident = _api_json("GET", "/v1/identity").get("identity") or {}
        droid = _api_json("GET", "/v1/droid/devices?refresh=1").get("devices") or {}
        emb = _api_json("GET", "/v1/embodiment/status")
    except Exception as exc:  # noqa: BLE001
        print(f"{_RED}Gateway offline at {_gateway_url()}{_RESET} ({exc})")
        print(f"Start it with: {_BOLD}./jaeger start{_RESET}")
        return 1

    gimbal = (droid.get("gimbal_camera") or {}).get("name") or "None detected"
    mc = (emb.get("minecraft") or {}).get("state") or {}
    print(f"{_BOLD}{_CYAN}JaegerAI Status{_RESET}  ({_GREEN}LIVE{_RESET} pid={health.get('pid')} uptime={health.get('uptime_s')}s)")
    print(f"  Identity:   {ident.get('ai_name', 'Jaeger')} · Owner: {ident.get('owner_name', 'Owner')}")
    print(f"  Model:      {health.get('model')} · Tools: {health.get('tools_count')}")
    print(f"  Memory:     {res.get('host_available_gb', '?')}/{res.get('host_total_gb', 32)} GB free · E-Stop: {'ON' if res.get('estop_active') else 'off'}")
    print(f"  Mind Loop:  mode={cog.get('mode', 'observing')} emotion={cog.get('emotion', 'calm')} ticks={cog.get('tick_count', 0)}")
    print(f"  Droid Mode: Gimbal={gimbal} · Mics={len(droid.get('microphones') or [])} · Speakers={len(droid.get('speakers') or [])}")
    print(f"  Minecraft:  paused={mc.get('paused', True)} · goal={mc.get('active_goal', '')}")
    print(f"  Studio UI:  {_webui_url()}")
    return 0


def _stream_turn(session_id: str, prompt: str) -> int:
    """Submit a turn and stream live SSE thinking/tool/text deltas to the terminal."""
    # Capture current seq cursor before submitting
    sub = _api_json("POST", f"/v1/sessions/{session_id}/runs", {"prompt": prompt})
    req_id = str(sub.get("request_id") or "")
    stream_url = f"{_gateway_url()}/v1/sessions/{session_id}/events?after_seq=0"
    req = urllib.request.Request(stream_url, method="GET")

    event_type = "message"
    saw_text = False
    started_thinking = False
    try:
        with urllib.request.urlopen(req, timeout=180.0) as resp:  # noqa: S310
            for raw_line in resp:
                line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                if not line:
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    payload_raw = line.split(":", 1)[1].strip()
                    try:
                        payload = json.loads(payload_raw)
                    except ValueError:
                        continue
                    if event_type == "thinking.delta":
                        delta = str(payload.get("delta") or "")
                        if delta:
                            if not started_thinking:
                                sys.stdout.write(f"{_DIM}[thinking] ")
                                started_thinking = True
                            sys.stdout.write(delta)
                            sys.stdout.flush()
                    elif event_type == "tool.started":
                        if started_thinking:
                            sys.stdout.write(f"{_RESET}\n")
                            started_thinking = False
                        print(f"{_YELLOW}⚙ tool:{payload.get('tool')}{_RESET} {_DIM}{json.dumps(payload.get('arguments') or {})[:120]}{_RESET}")
                    elif event_type == "tool.completed":
                        print(f"{_GREEN}✓ {payload.get('tool')}{_RESET} {_DIM}({payload.get('duration_ms', 0)}ms){_RESET}")
                    elif event_type == "tool.failed":
                        print(f"{_RED}✗ {payload.get('tool')}: {payload.get('error')}{_RESET}")
                    elif event_type == "text.delta":
                        if started_thinking:
                            sys.stdout.write(f"{_RESET}\n")
                            started_thinking = False
                        delta = str(payload.get("delta") or "")
                        if delta:
                            saw_text = True
                            sys.stdout.write(delta)
                            sys.stdout.flush()
                    elif event_type in ("run.completed", "run.failed"):
                        ev_rid = str(payload.get("request_id") or "")
                        if req_id and ev_rid and ev_rid != req_id:
                            continue
                        if started_thinking:
                            sys.stdout.write(f"{_RESET}\n")
                        if saw_text:
                            print()
                        elif payload.get("final_text"):
                            print(payload["final_text"])
                        if event_type == "run.failed":
                            print(f"{_RED}Run failed: {payload.get('error')}{_RESET}")
                            return 1
                        return 0
    except KeyboardInterrupt:
        print(f"\n{_DIM}[interrupted]{_RESET}")
        return 130
    return 0


def _interactive_chat() -> int:
    try:
        health = _api_json("GET", "/health")
        ident = _api_json("GET", "/v1/identity").get("identity") or {}
    except Exception:  # noqa: BLE001
        print(f"{_RED}Jaeger Gateway is not running on {_gateway_url()}.{_RESET}")
        print(f"Start it first with: {_BOLD}./jaeger start{_RESET}")
        return 1

    ai_name = ident.get("ai_name") or "Jaeger"
    sess = _api_json("POST", "/v1/sessions", {"title": "Terminal Chat"})["session"]
    sid = sess["session_id"]

    print(f"{_BOLD}{_CYAN}━━━ {ai_name} Terminal Chat ━━━{_RESET}")
    print(f"{_DIM}Model: {health.get('model')} · Session: {sid} · Studio UI: {_webui_url()}{_RESET}")
    print(f"{_DIM}Commands: /status  /droid  /identity  /goals  /clear  /help  /quit{_RESET}\n")

    while True:
        try:
            user_text = input(f"{_BOLD}you>{_RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_text:
            continue
        if user_text in ("/quit", "/exit", "exit", "quit"):
            return 0
        if user_text == "/help":
            print("Slash commands: /status, /droid, /identity, /goals, /clear, /open, /quit")
            continue
        if user_text == "/status":
            _print_status()
            continue
        if user_text == "/droid":
            d = _api_json("GET", "/v1/droid/devices?refresh=1").get("devices") or {}
            print(json.dumps({"gimbal": d.get("gimbal_camera"), "mics": [m["name"] for m in d.get("microphones") or []], "speakers": [s["name"] for s in d.get("speakers") or []]}, indent=2))
            continue
        if user_text == "/identity":
            print(json.dumps(_api_json("GET", "/v1/identity").get("identity") or {}, indent=2))
            continue
        if user_text == "/goals":
            goals = _api_json("GET", "/v1/memory/goals").get("goals") or []
            if not goals:
                print(f"{_DIM}No persistent goals yet.{_RESET}")
            for g in goals:
                print(f"  [{g['domain']}] P{g['priority']} {g['title']} ({g['status']})")
            continue
        if user_text == "/open":
            webbrowser.open(_webui_url())
            continue
        if user_text == "/clear":
            sess = _api_json("POST", "/v1/sessions", {"title": "Terminal Chat"})["session"]
            sid = sess["session_id"]
            print(f"{_DIM}Started fresh session: {sid}{_RESET}")
            continue

        print(f"{_CYAN}{ai_name}>{_RESET} ", end="", flush=True)
        _stream_turn(sid, user_text)
        print()


def _print_help() -> None:
    print(
        f"""{_BOLD}JaegerAI Operator CLI{_RESET}

Usage:
  ./jaeger                  Interactive streaming terminal chat (TUI)
  ./jaeger chat             Interactive streaming terminal chat (TUI)
  ./jaeger ask "<prompt>"   Run a single prompt against the live Gateway
  ./jaeger start            Start standalone Gateway (:33418) + 5-Tab Studio WebUI (:8790)
  ./jaeger status           Show live Gateway, 32 GB RAM, Mind Loop, Droid & Minecraft status
  ./jaeger doctor [--json]  Verify all modular packages, binaries, WebUI & Gateway
  ./jaeger setup [flags]    Run one-command reproducible setup (scripts/setup.sh)
  ./jaeger verify [target]  Run full verification suite (scripts/verify.sh)
  ./jaeger open             Open 5-Tab Studio WebUI in default browser ({_webui_url()})
"""
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "chat"
    rest = args[1:]

    if cmd in ("-h", "--help", "help"):
        _print_help()
        return 0
    if cmd == "chat":
        return _interactive_chat()
    if cmd == "ask":
        prompt = " ".join(rest).strip()
        if not prompt:
            print("Usage: ./jaeger ask \"<prompt>\"", file=sys.stderr)
            return 2
        sess = _api_json("POST", "/v1/sessions", {"title": prompt[:48]})["session"]
        return _stream_turn(sess["session_id"], prompt)
    if cmd == "start":
        from jaeger_gateway import serve_modular_gateway

        asyncio.run(serve_modular_gateway())
        return 0
    if cmd == "status":
        return _print_status()
    if cmd == "doctor":
        return subprocess.call([sys.executable, "-B", str(REPO_ROOT / "scripts/doctor.py"), *rest])
    if cmd == "setup":
        return subprocess.call(["bash", str(REPO_ROOT / "scripts/setup.sh"), *rest])
    if cmd == "verify":
        return subprocess.call(["bash", str(REPO_ROOT / "scripts/verify.sh"), *(rest or ["all"])])
    if cmd == "open":
        webbrowser.open(_webui_url())
        print(f"Opened {_webui_url()}")
        return 0

    print(f"Unknown command: {cmd!r}", file=sys.stderr)
    _print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
