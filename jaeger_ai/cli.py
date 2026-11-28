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
                        elif saw_text:
                            sys.stdout.write("\n")
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
    print(f"{_DIM}Commands: /status  /model  /briefing  /context  /tools  /skills  /cron  /search  /droid  /goals  /clear  /help  /quit{_RESET}\n")

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
            print(
                "Slash commands: /status, /model [id|routing ...], /briefing, /context, /tools [q], /skills, "
                "/cron, /search <q>, /droid, /identity, /goals, /clear, /open, /quit"
            )
            continue
        if user_text == "/status":
            _print_status()
            continue
        if user_text == "/briefing":
            _cmd_briefing()
            continue
        if user_text == "/model" or user_text.startswith("/model "):
            target = user_text[6:].strip()
            _cmd_model(target.split() if target else [])
            continue
        if user_text == "/context":
            _print_context()
            continue
        if user_text == "/tools" or user_text.startswith("/tools "):
            q = user_text[6:].strip()
            _cmd_tools([q] if q else [])
            continue
        if user_text == "/skills":
            _cmd_skills([])
            continue
        if user_text == "/cron":
            _cmd_cron(["list"])
            continue
        if user_text.startswith("/search "):
            q = user_text[8:].strip()
            if q:
                import urllib.parse
                hits = _api_json("GET", f"/v1/chat/search?{urllib.parse.urlencode({'q': q, 'limit': 8})}").get("results") or []
                if not hits:
                    print(f"{_DIM}No matching past messages.{_RESET}")
                for h in hits:
                    print(f"  [{h['session_title']} #{h['id']}] ({h['role']}) {h['excerpt']}")
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


def _print_context() -> int:
    health = _api_json("GET", "/health")
    res = _api_json("GET", "/v1/system/resources").get("resources") or {}
    facts = _api_json("GET", "/v1/memory/facts").get("facts") or []
    skills = _api_json("GET", "/v1/skills").get("skills") or []
    print(f"{_BOLD}{_CYAN}Jaeger Context & Budget{_RESET}")
    print(f"  Model:        {health.get('model')}")
    print(f"  Active tools: {health.get('tools_count')}")
    print(f"  Saved facts:  {len(facts)}")
    print(f"  Skills found: {len(skills)}")
    print(f"  Host memory:  {res.get('host_available_gb', '?')}/{res.get('host_total_gb', 32)} GB free")
    print(f"  Browser:      {(health.get('browser') or {}).get('mode', 'unknown')}")
    return 0


def _cmd_config() -> int:
    health = _api_json("GET", "/health")
    ident = _api_json("GET", "/v1/identity").get("identity") or {}
    ch = _api_json("GET", "/v1/channels/status")
    hosts = _api_json("GET", "/v1/remote/hosts").get("hosts") or []
    print(f"{_BOLD}{_CYAN}JaegerAI Configuration{_RESET}")
    print(f"  State dir:    {health.get('state_dir')}")
    print(f"  Workspace:    {health.get('workspace')}")
    print(f"  Identity:     {ident.get('ai_name', 'Jaeger')} · Owner: {ident.get('owner_name', 'Owner')}")
    print(f"  Model:        {health.get('model')}")
    print(f"  Browser:      {(health.get('browser') or {}).get('mode', 'unknown')}")
    adapters = (ch.get("channels") or {}).get("configured_adapters") or []
    print(f"  Channels:     {', '.join(adapters) or 'local_log'}")
    print(f"  Remote hosts: {', '.join(h['alias'] for h in hosts) or '(none)'}")
    return 0


def _cmd_model(args: list[str]) -> int:
    if args and args[0] == "routing":
        rest = args[1:]
        if not rest:
            data = _api_json("GET", "/v1/models/routing")
            r = data.get("routing") or {}
            print(f"{_BOLD}{_CYAN}Hybrid Model Routing{_RESET} (active: {data.get('active')})")
            print(f"  primary:    {r.get('primary') or '(default)'}")
            print(f"  background: {r.get('background') or '(same as primary)'}")
            print(f"  vision:     {r.get('vision') or 'qwen3-vl:8b-instruct'}")
            print(f"  fallback:   {r.get('fallback') or '(none)'}")
            return 0
        if len(rest) >= 2 and rest[0] in ("primary", "background", "vision", "fallback"):
            tier, val = rest[0], "" if rest[1] in ("none", "clear", "-") else rest[1]
            res = _api_json("PUT", "/v1/models/routing", {tier: val})
            print(f"{_GREEN}Updated {tier}:{_RESET} {json.dumps(res.get('routing'))}")
            return 0
        print("Usage: ./jaeger model routing [primary|background|vision|fallback <model_id|none>]")
        return 2
    if args:
        res = _api_json("POST", "/v1/models/select", {"model": args[0]})
        print(f"{_GREEN}Active model:{_RESET} {res.get('active')}")
        return 0
    info = _api_json("GET", "/v1/models")
    active = info.get("active") or ""
    r = info.get("routing") or {}
    print(f"{_BOLD}Active model:{_RESET} {active}")
    if any(r.get(k) for k in ("background", "fallback")):
        print(f"{_DIM}Routing: background={r.get('background') or '-'} · vision={r.get('vision') or '-'} · fallback={r.get('fallback') or '-'}{_RESET}")
    for m in info.get("models") or []:
        mid = m.get("id") or ""
        mark = f"{_GREEN}*{_RESET}" if mid == active else " "
        print(f"  {mark} {mid}")
    return 0


def _cmd_briefing() -> int:
    data = _api_json("GET", "/v1/cognition/briefing")
    print(f"{_BOLD}{_CYAN}While You Were Out{_RESET}")
    print(data.get("summary") or "All quiet.")
    return 0


def _cmd_onboard() -> int:
    st = _api_json("GET", "/v1/onboarding/status")
    ident = st.get("identity") or {}
    routing = st.get("model_routing") or {}
    print(f"{_BOLD}{_CYAN}JaegerAI Day-1 Setup Wizard{_RESET}")
    print(f"Press Enter to keep the value in [brackets].\n")
    owner = input(f"Your name [{ident.get('owner_name') or 'Owner'}]: ").strip()
    ai_name = input(f"Assistant name [{ident.get('ai_name') or 'Jaeger'}]: ").strip()
    mission = input(f"What should {ai_name or ident.get('ai_name') or 'Jaeger'} help you with? [{ident.get('mission') or ''}]: ").strip()
    primary = input(f"Primary model (cloud or local) [{routing.get('primary') or ''}]: ").strip()
    background = input(f"Background/autonomy model (fast/cheap, optional) [{routing.get('background') or ''}]: ").strip()
    fallback = input(f"Offline local fallback model (optional) [{routing.get('fallback') or ''}]: ").strip()
    first_goal = input("First multi-day goal to track (optional): ").strip()
    payload: dict[str, Any] = {}
    if owner:
        payload["owner_name"] = owner
    if ai_name:
        payload["ai_name"] = ai_name
    if mission:
        payload["mission"] = mission
    if primary:
        payload["primary_model"] = primary
    if background:
        payload["background_model"] = background
    if fallback:
        payload["fallback_model"] = fallback
    if first_goal:
        payload["first_goal"] = first_goal
    res = _api_json("POST", "/v1/onboarding/complete", payload)
    print(f"\n{_GREEN}Onboarding saved!{_RESET} Starter skills ready: {res.get('starter_skills_count', 0)}")
    if res.get("next_steps"):
        print(f"{_DIM}Optional next steps:{_RESET}")
        for step in res["next_steps"]:
            print(f"  • {step}")
    return 0


def _cmd_avatar(args: list[str]) -> int:
    from jaeger_avatar import DEFAULT_AVATAR_PORT, DEFAULT_FACE, launch_avatar_app, probe_avatar_link

    face = DEFAULT_FACE
    port = int(os.environ.get("JAEGER_AVATAR_PORT") or DEFAULT_AVATAR_PORT)
    browser = False
    check = False
    no_launch = False
    gif = False
    out_path = "/tmp/lilith_demo.gif"
    it = iter(args)
    for tok in it:
        if tok == "--face":
            face = next(it, DEFAULT_FACE)
        elif tok == "--port":
            port = int(next(it, str(port)))
        elif tok == "--browser":
            browser = True
        elif tok == "--check":
            check = True
        elif tok == "--no-launch":
            no_launch = True
        elif tok == "--gif":
            gif = True
        elif tok == "--out":
            out_path = next(it, out_path)
        elif tok in ("-h", "--help"):
            print(
                "Usage: ./jaeger avatar [--face vita] [--port 8791] [--browser] "
                "[--check [--no-launch]] [--gif [--out /tmp/lilith_demo.gif]]"
            )
            return 0
    if gif:
        script = REPO_ROOT / "dev" / "scripts" / "lilith_demo.py"
        if not script.is_file():
            print(f"{_RED}missing demo script: {script}{_RESET}", file=sys.stderr)
            return 1
        venv_py = Path(os.environ.get("JAEGER_VENV") or (Path.home() / ".jaeger" / "venv")) / "bin" / "python"
        py = str(venv_py) if venv_py.is_file() else sys.executable
        print(f"{_DIM}running {script.name}...{_RESET}")
        return subprocess.run([py, str(script)], check=False, cwd=str(REPO_ROOT)).returncode
    if check:
        try:
            result = probe_avatar_link(face=face, port=port, browser=browser, launch_if_needed=not no_launch)
        except (FileNotFoundError, TimeoutError, RuntimeError) as exc:
            print(f"{_YELLOW}{exc}{_RESET}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("serving") else 1
    try:
        url = launch_avatar_app(face=face, port=port, browser=browser)
        print(f"{_GREEN}Living Avatar running:{_RESET} {url}")
        if browser:
            print(f"{_DIM}  serving only (no window); open the URL in a browser{_RESET}")
        return 0
    except FileNotFoundError as exc:
        print(f"{_YELLOW}{exc}{_RESET}", file=sys.stderr)
        print("Clone sibling JaegerAvatar or set JAEGER_AVATAR_HOME=/path/to/JaegerAvatar.", file=sys.stderr)
        return 1
    except TimeoutError as exc:
        print(f"{_RED}{exc}{_RESET}", file=sys.stderr)
        return 1


def _cmd_tools(args: list[str]) -> int:
    q = " ".join(args).strip().lower()
    tools = _api_json("GET", "/v1/tools").get("tools") or []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for t in tools:
        hay = f"{t.get('name', '')} {t.get('description', '')} {t.get('source', '')}".lower()
        if q and q not in hay:
            continue
        grouped.setdefault(str(t.get("source") or "builtin"), []).append(t)
    total = sum(len(v) for v in grouped.values())
    print(f"{_BOLD}Enabled Tools ({total}){_RESET}")
    for src in sorted(grouped):
        print(f"  {_CYAN}{src}{_RESET}")
        for t in sorted(grouped[src], key=lambda x: x.get("name", "")):
            ro = "ro" if t.get("read_only") else "rw"
            print(f"    {_GREEN}✓{_RESET} {t['name']} [{ro}] — {str(t.get('description') or '')[:90]}")
    return 0


def _cmd_skills(args: list[str]) -> int:
    q = " ".join(args).strip().lower()
    skills = _api_json("GET", "/v1/skills").get("skills") or []
    shown = [s for s in skills if not q or q in str(s.get("name", "")).lower()]
    print(f"{_BOLD}Discovered Skills ({len(shown)}){_RESET}")
    for s in shown:
        print(f"  {_GREEN}✓{_RESET} {s['name']} [{s.get('security_verdict', 'safe')}] — {s['path']}")
    return 0


def _cmd_cron(args: list[str]) -> int:
    sub = args[0] if args else "list"
    sid = "sess_jaeger_chat"
    if sub == "list":
        jobs = _api_json("GET", f"/v1/sessions/{sid}/jobs").get("jobs") or []
        print(f"{_BOLD}Scheduled Jobs ({len(jobs)}){_RESET}")
        for j in jobs:
            sched = j.get("cron_expr") or (f"every {j.get('interval_s')}s" if j.get("interval_s") else "one-shot")
            print(f"  [{j['status']}] {j['job_id']} ({sched}) series={j.get('series_id') or '-'} — {str(j.get('prompt') or '')[:80]}")
        return 0
    if sub == "add" and len(args) >= 3:
        cron_expr, prompt = args[1], " ".join(args[2:]).strip()
        res = _api_json("POST", f"/v1/sessions/{sid}/jobs", {"cron_expr": cron_expr, "prompt": prompt})
        job = res.get("job") or {}
        print(f"{_GREEN}Scheduled:{_RESET} {job.get('job_id')} (series={job.get('series_id')}, cron={job.get('cron_expr')})")
        return 0
    if sub in ("pause", "resume", "cancel") and len(args) >= 2:
        target = args[1]
        if target.startswith("series_"):
            status_map = {"pause": "paused", "resume": "active", "cancel": "cancelled"}
            res = _api_json("PATCH", f"/v1/sessions/{sid}/job-series/{target}", {"status": status_map[sub]})
            print(json.dumps(res, indent=2))
            return 0
        if sub == "cancel":
            res = _api_json("POST", f"/v1/sessions/{sid}/jobs/{target}/cancel", {})
            print(json.dumps(res, indent=2))
            return 0
    print("Usage: ./jaeger cron [list | add \"<5-field-cron>\" \"<prompt>\" | pause <series_id> | resume <series_id> | cancel <job_or_series_id>]")
    return 2


def _cmd_channels(args: list[str]) -> int:
    sub = args[0] if args else "status"
    if sub == "status":
        data = _api_json("GET", "/v1/channels/status")
        print(json.dumps({"channels": data.get("channels"), "config": data.get("config"), "ingress": data.get("ingress")}, indent=2))
        return 0
    if sub == "setup":
        state_dir = Path(os.environ.get("JAEGER_STATE_DIR") or (Path.home() / ".jaeger")).expanduser().resolve()
        cfg_path = state_dir / "channels.json"
        existing = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
        print(f"{_BOLD}{_CYAN}Jaeger Channels Setup Wizard{_RESET} ({cfg_path})")
        print("Leave any prompt blank to skip. Restart Gateway after saving (`./jaeger stack down gateway && ./jaeger stack up gateway`).\n")
        tg_tok = input("Telegram Bot Token: ").strip()
        if tg_tok:
            tg_chats = [c.strip() for c in input("Telegram Allowed Chat IDs (comma-separated): ").split(",") if c.strip()]
            existing["telegram"] = {"enabled": True, "bot_token": tg_tok, "allowed_chat_ids": tg_chats, "poll_inbound": True, "auto_reply_owner": False}
        dc_hook = input("Discord Webhook URL (or leave blank): ").strip()
        if dc_hook:
            existing["discord"] = {"enabled": True, "webhook_url": dc_hook}
        sl_hook = input("Slack Webhook URL (or leave blank): ").strip()
        if sl_hook:
            existing["slack"] = {"enabled": True, "webhook_url": sl_hook}
        im_ans = input("Enable macOS iMessage adapter? [y/N]: ").strip().lower()
        if im_ans in ("y", "yes"):
            existing["imessage"] = {"enabled": True}
        state_dir.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        print(f"{_GREEN}Saved channel configuration to {cfg_path}{_RESET}")
        return 0
    print("Usage: ./jaeger channels [status | setup]")
    return 2


def _cmd_remote(args: list[str]) -> int:
    sub = args[0] if args else "list"
    if sub == "list":
        hosts = _api_json("GET", "/v1/remote/hosts").get("hosts") or []
        print(f"{_BOLD}Allowlisted SSH Hosts ({len(hosts)}){_RESET}")
        for h in hosts:
            target = f"{h['user']}@{h['hostname']}" if h.get("user") else h["hostname"]
            print(f"  {_GREEN}✓{_RESET} {h['alias']} -> {target}:{h.get('port', 22)} (enabled={h.get('enabled')})")
        return 0
    if sub == "add" and len(args) >= 3:
        alias, hostname = args[1], args[2]
        user, port = "", 22
        it = iter(args[3:])
        for tok in it:
            if tok == "--user":
                user = next(it, "")
            elif tok == "--port":
                port = int(next(it, "22"))
        res = _api_json("PUT", f"/v1/remote/hosts/{alias}", {"hostname": hostname, "user": user, "port": port, "enabled": True})
        print(f"{_GREEN}Saved remote host:{_RESET} {json.dumps(res.get('host'))}")
        return 0
    if sub == "remove" and len(args) >= 2:
        res = _api_json("DELETE", f"/v1/remote/hosts/{args[1]}")
        print(json.dumps(res))
        return 0
    print("Usage: ./jaeger remote [list | add <alias> <hostname> [--user u] [--port 22] | remove <alias>]")
    return 2


def _cmd_autonomy(args: list[str]) -> int:
    sub = args[0] if args else "status"
    if sub == "status":
        data = _api_json("GET", "/v1/cognition/actions?limit=5")
        st = data.get("status") or {}
        cfg = st.get("config") or {}
        dr = st.get("drives") or {}
        print(f"{_BOLD}{_CYAN}Jaeger Autonomous Self-Actions{_RESET}")
        print(f"  Enabled:    {'ON' if cfg.get('enabled') else 'OFF'} · Cooldown: {cfg.get('cooldown_s')}s · Cap: {st.get('actions_last_hour', 0)}/{cfg.get('max_actions_per_hour')}/hr")
        print(f"  Drives:     curiosity={dr.get('curiosity')} momentum={dr.get('goal_momentum')} social={dr.get('social')} energy={dr.get('energy')}")
        print(f"  Next turn:  in {st.get('next_eligible_in_s', 0)}s")
        for act in data.get("actions") or []:
            print(f"  • [{act['kind']}] {act['summary'][:90]}")
        return 0
    if sub in ("on", "off"):
        res = _api_json("POST", "/v1/cognition/autonomy", {"enabled": sub == "on"})
        print(f"{_GREEN}Autonomy {'enabled' if sub == 'on' else 'paused'}.{_RESET} ({json.dumps(res.get('status', {}).get('config'))})")
        return 0
    if sub == "step":
        res = _api_json("POST", "/v1/cognition/autonomy", {"trigger_now": True}, timeout=60.0)
        print(json.dumps(res.get("triggered"), indent=2))
        return 0
    if sub == "log":
        actions = _api_json("GET", "/v1/cognition/actions?limit=20").get("actions") or []
        print(f"{_BOLD}Initiative Journal ({len(actions)}){_RESET}")
        for act in actions:
            print(f"  [{act['status']}] {act['kind']} — {act['summary']}")
        return 0
    if sub == "elevated":
        mode = args[1] if len(args) >= 2 else "status"
        if mode in ("on", "off"):
            res = _api_json("POST", "/v1/cognition/autonomy", {"elevated": mode == "on"})
            print(f"{_GREEN}Elevated mode:{_RESET} {json.dumps(res.get('execution_mode'))}")
            return 0
        health = _api_json("GET", "/health")
        print(json.dumps({"elevated": health.get("elevated", False), "sandbox": health.get("sandbox")}, indent=2))
        return 0
    print("Usage: ./jaeger autonomy [status | on | off | step | log | elevated [on|off|status]]")
    return 2


def _cmd_minecraft(args: list[str]) -> int:
    sub = args[0] if args else "status"
    if sub == "status":
        mc = _api_json("GET", "/v1/embodiment/status").get("minecraft") or {}
        print(json.dumps(mc, indent=2))
        return 0
    if sub == "connect":
        body: dict[str, Any] = {"action": "connect", "params": {}}
        if len(args) >= 2:
            body["params"]["host"] = args[1]
        if len(args) >= 3:
            body["params"]["port"] = int(args[2])
        res = _api_json("POST", "/v1/embodiment/minecraft/act", body, timeout=45.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "disconnect":
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "disconnect", "params": {}})
        print(json.dumps(res, indent=2))
        return 0
    if sub == "goal" and len(args) >= 2:
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "set_goal", "params": {"goal": " ".join(args[1:])}})
        print(json.dumps(res, indent=2))
        return 0
    if sub == "follow" and len(args) >= 2:
        dist = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 3
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "follow_player", "params": {"player": args[1], "distance": dist}}, timeout=30.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "come" and len(args) >= 2:
        dist = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 3
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "go_to_player", "params": {"player": args[1], "distance": dist}}, timeout=45.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "give" and len(args) >= 3:
        cnt = int(args[3]) if len(args) >= 4 and args[3].isdigit() else 1
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "give_to_player", "params": {"player": args[1], "item": args[2], "count": cnt}}, timeout=45.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "eat":
        item = args[1] if len(args) >= 2 else ""
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "eat", "params": {"item": item}}, timeout=20.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "sleep":
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "go_to_bed", "params": {}}, timeout=30.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "stop":
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "stop_actions", "params": {}}, timeout=15.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "mode" and len(args) >= 3:
        enabled = args[2].lower() in ("on", "true", "1", "yes")
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "set_mode", "params": {"mode": args[1], "enabled": enabled}}, timeout=15.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "chat" and len(args) >= 2:
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "chat", "params": {"message": " ".join(args[1:])}}, timeout=20.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "inbox":
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "read_chat", "params": {}}, timeout=15.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "players":
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "nearby_players", "params": {}}, timeout=15.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "save" and len(args) >= 2:
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "save_location", "params": {"name": args[1], "notes": " ".join(args[2:])}}, timeout=15.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "places":
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "list_locations", "params": {}}, timeout=15.0)
        print(json.dumps(res, indent=2))
        return 0
    if sub == "goto" and len(args) >= 2:
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "goto_location", "params": {"name": args[1]}}, timeout=45.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "guard":
        radius = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 10
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "guard_area", "params": {"radius": radius}}, timeout=20.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "build" and len(args) >= 2:
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "build_blueprint", "params": {"blueprint": args[1]}}, timeout=60.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "join":
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "join_guide", "params": {}}, timeout=15.0)
        print(json.dumps(res, indent=2))
        return 0
    if sub == "lan" and len(args) >= 2:
        enabled = args[1].lower() in ("on", "true", "1", "yes")
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "lan_broadcast", "params": {"enabled": enabled}}, timeout=15.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if sub == "step" and len(args) >= 2:
        res = _api_json("POST", "/v1/embodiment/minecraft/act", {"action": "step", "params": {"code": " ".join(args[1:])}}, timeout=60.0)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    print(
        "Usage: ./jaeger minecraft [status | connect [host] [port] | disconnect | goal \"<goal>\" | "
        "follow <player> [dist] | come <player> | give <player> <item> [count] | eat [item] | "
        "sleep | guard [radius] | build <shelter|monument|farm|town_hall> | save <name> | places | "
        "goto <name> | join | lan <on|off> | stop | mode <name> <on|off> | chat \"<msg>\" | inbox | players | step \"<js>\"]"
    )
    return 2


def _open_desktop_app() -> int:
    app_path = Path(os.environ.get("JAEGER_APP_PATH") or "/Applications/JaegerAI.app")
    if not app_path.exists():
        print(f"{_RED}JaegerAI app not found at {app_path}{_RESET}", file=sys.stderr)
        return 1
    if sys.platform == "darwin":
        rc = subprocess.call(["open", str(app_path)])
    else:
        rc = 0 if webbrowser.open(app_path.as_uri()) else 1
    if rc == 0:
        print(f"Opened {app_path}")
    return rc


def _print_help() -> None:
    print(
        f"""{_BOLD}JaegerAI Operator CLI{_RESET}

Usage:
  ./jaeger                          Interactive streaming terminal chat (TUI)
  ./jaeger chat                     Interactive streaming terminal chat (TUI)
  ./jaeger ask "<prompt>"           Run a single prompt against the live Gateway
  ./jaeger start                    Start standalone Gateway (:33418) + 5-Tab Studio WebUI (:8790)
  ./jaeger stop [svc...] [--json]   Stop Gateway (or specified stack services) cleanly
  ./jaeger restart [svc...] [--json] Restart Gateway (or specified stack services) cleanly
  ./jaeger stack <cmd> [args]       Manage launchd stack (status | up | down | restart) [--json]
  ./jaeger status                   Show live Gateway, 32 GB RAM, Mind Loop, Droid & Minecraft status
  ./jaeger config                   Inspect active paths, identity, model, channels & remote hosts
  ./jaeger model [id | routing ...] List models, switch active model, or configure hybrid routing tiers
  ./jaeger onboard                  Run the 30-second Day-1 setup wizard (identity, routing & first goal)
  ./jaeger briefing                 Show Jaeger's "While You Were Out" status & self-action briefing
  ./jaeger avatar [--face vita]     Launch or check the optional sibling JaegerAvatar living stage (:8791)
  ./jaeger tools [query]            List or search enabled tools grouped by package
  ./jaeger skills [query]           List discovered SKILL.md playbooks and security scan status
  ./jaeger cron [list|add|...]      Manage recurring 5-field cron & scheduled jobs
  ./jaeger channels [status|setup]  Inspect messaging channels or run interactive channel setup wizard
  ./jaeger remote [list|add|remove] Manage owner-allowlisted SSH remote hosts (e.g. rack PC)
  ./jaeger autonomy [status|on|off|step|log] Control & audit Jaeger's persistent self-actions
  ./jaeger minecraft [status|connect|...]    Inspect or connect Jaeger's live Mineflayer Minecraft body
  ./jaeger doctor [--json]          Verify all modular packages, binaries, WebUI & Gateway
  ./jaeger setup [flags]            Run one-command reproducible setup (scripts/setup.sh)
  ./jaeger verify [target]          Run full verification suite (scripts/verify.sh)
  ./jaeger open                     Open 5-Tab Studio WebUI in default browser ({_webui_url()})
  ./jaeger app                      Open the JaegerAI macOS desktop & menubar app (/Applications/JaegerAI.app)
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
    if cmd == "stack":
        from .stack import main as stack_main

        return stack_main(rest)
    if cmd == "stop":
        from .stack import main as stack_main

        return stack_main(["down", *rest])
    if cmd == "restart":
        from .stack import main as stack_main

        return stack_main(["restart", *rest])
    if cmd == "app":
        return _open_desktop_app()
    if cmd == "status":
        return _print_status()
    if cmd == "config":
        return _cmd_config()
    if cmd == "model":
        return _cmd_model(rest)
    if cmd == "onboard":
        return _cmd_onboard()
    if cmd == "briefing":
        return _cmd_briefing()
    if cmd == "avatar":
        return _cmd_avatar(rest)
    if cmd == "tools":
        return _cmd_tools(rest)
    if cmd == "skills":
        return _cmd_skills(rest)
    if cmd == "cron":
        return _cmd_cron(rest)
    if cmd == "channels":
        return _cmd_channels(rest)
    if cmd == "remote":
        return _cmd_remote(rest)
    if cmd == "autonomy":
        return _cmd_autonomy(rest)
    if cmd == "minecraft":
        return _cmd_minecraft(rest)
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
