#!/usr/bin/env python3
"""Audit guard: keeps the fixes from repo-audit-2026-11-16 from regressing.

Not a test suite. Each check looks at the repo (structure) or the running Mac
(live endpoints, launchd, the session store opened read-only) and reports
PASS / FAIL / OPEN. A check whose audit item is marked resolved must PASS;
any FAIL on a resolved item exits 1, so run this before every push:

    python3 scripts/audit-guard.py            # table
    python3 scripts/audit-guard.py --markdown # for the tracker

Never prints secrets: config files are only checked for the presence of a key.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()
JAEGER = HOME / ".jaeger"
REMOVED = HOME / "Desktop" / "Jaeger-removed-features-2026-11-16"
GATEWAY = os.environ.get("JAEGER_GATEWAY_URL", "http://127.0.0.1:33418")
VOICE = "http://127.0.0.1:8794"
SUCCESS_FLOOR = 0.90  # turn success over the last 24h (completed / non-cancelled)
STALE_HOURS = 24


def _get(url: str, timeout: float = 5.0) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)
    try:
        return code, json.loads(body)
    except Exception:
        return code, body[:200]


def _py_files(*roots: str):
    for root in roots:
        base = REPO / root
        if base.is_file():
            yield base
            continue
        for p in base.rglob("*.py"):
            parts = set(p.parts)
            if "tests" in parts or "test" in parts or "__pycache__" in parts or p.name.startswith("test_"):
                continue
            yield p


def _grep(pattern: str, *roots: str) -> list[str]:
    rx = re.compile(pattern)
    hits = []
    for p in _py_files(*roots):
        try:
            for i, line in enumerate(p.read_text("utf-8", "ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p.relative_to(REPO)}:{i}")
        except OSError:
            pass
    return hits


def _db():
    path = JAEGER / "gateway_sessions.sqlite3"
    # Plain connect (WAL needs the -shm file); the guard only ever SELECTs.
    return sqlite3.connect(str(path), timeout=5)


def _launchctl_list() -> dict[str, tuple[str, str]]:
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    jobs = {}
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3 and parts[2].startswith("com.jenkinsrobotics.jaeger"):
            jobs[parts[2]] = (parts[0], parts[1])
    return jobs


# ── checks: each returns (ok, detail) ─────────────────────────────────────

def c_no_openclaw_parity():
    hits = _grep(r"openclaw-parity", "jaeger_ai")
    return not hits, ", ".join(hits[:3]) or "gateway describes itself as single-engine"


def c_gateway_health():
    code, d = _get(f"{GATEWAY}/health")
    if not isinstance(d, dict):
        return False, f"HTTP {code}: {d}"
    bad = [k for k, v in (d.get("checks") or {}).items() if isinstance(v, dict) and v.get("ok") is False]
    return d.get("status") == "ok" and not bad, f"HTTP {code} status={d.get('status')} failing={bad or 'none'} arch={d.get('architecture')}"


def c_voice_health():
    code, d = _get(f"{VOICE}/health")
    return code == 200 and isinstance(d, dict) and d.get("ok") is True, f"HTTP {code}"


SERVICE_JOBS = ["gateway", "bridge", "mcp-http", "voice", "channels", "droid"]


def c_launchd_running():
    jobs = _launchctl_list()
    missing = [j for j in SERVICE_JOBS if jobs.get(f"com.jenkinsrobotics.jaeger-{j}", ("-",))[0] in ("-", None)]
    return not missing, f"not running: {missing}" if missing else f"{len(SERVICE_JOBS)} service jobs running"


def c_stack_boot_wait():
    src = (REPO / "jaeger_ai/core/runtime/stack.py").read_text()
    m = re.search(r'"--wait", type=float, default=([0-9.]+)', src)
    ok = bool(m) and float(m.group(1)) >= 90
    return ok, f"stack up --wait default {m.group(1) if m else 'missing'}s (boot job no longer times out at 25s)"


def c_single_turn_path():
    import ast
    targets = {
        "jaeger_ai/main.py": {"_run_turn", "run_for_voice", "run_command", "run_worker_turn",
                              "_run_subordinate_react", "_run_direct_model_runner"},
        "jaeger_ai/core/frameworks/native_runs.py": {"jaeger_turn", "_in_process_jaeger_turn"},
    }
    bad = []
    for rel, names in targets.items():
        src = (REPO / rel).read_text()
        for node in ast.parse(src).body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                body = ast.get_source_segment(src, node) or ""
                gateway = "run_gateway_turn" in body or "_jaeger_gateway_turn" in body or "return jaeger_turn(" in body
                if not gateway or (node.end_lineno - node.lineno) > 25:
                    bad.append(f"{rel}:{node.name}")
    return not bad, ("in-process runners left: " + ", ".join(bad)) if bad else "every entry point submits to the Gateway (turn_client)"


def c_one_scheduler():
    # The only runner is the Gateway background producer; nobody else starts a CronRunner.
    hits = [h for h in _grep(r"CronRunner\(", "jaeger_ai", "packages/jaeger-agent/jaeger_agent")
            if not h.startswith(("jaeger_ai/core/runtime/background_producers.py", "packages/jaeger-agent/jaeger_agent/background/cron_runner.py"))]
    extra = [p for p in ("packages/jaeger-agent/jaeger_agent/background/cron.py",) if (REPO / p).exists()]
    return not hits and not extra, (", ".join(hits + extra) or "Gateway background producer only")


def c_one_heartbeat():
    # One agent heartbeat (core/runtime/heartbeat.py via background_producers). The droid
    # life loop is the body's reflex loop and must never start agent turns itself.
    life = (REPO / "jaeger_ai/features/droid/life.py")
    life_turns = life.exists() and bool(re.search(r"submit_turn|/turns", life.read_text()))
    try:
        db = sqlite3.connect(str(JAEGER / "instances/jaeger/memory/state.db"), timeout=5)
        n = db.execute("select count(*) from schedules where status='active' and (schedule_id like '%heartbeat%' or prompt like 'Heartbeat%')").fetchone()[0]
        db.close()
    except Exception as e:  # noqa: BLE001
        return False, f"state.db error {e}"
    return n == 0 and not life_turns, f"heartbeat schedules active: {n}; droid life starts turns: {life_turns}"


def c_no_hermes_webui():
    exists = (REPO / "jaeger_ai/features/webui").exists()
    code, d = _get("http://127.0.0.1:8790/api/health")
    served = code == 200 and isinstance(d, dict) and d.get("served_by") == "gateway"
    return not exists and served, ("features/webui present; " if exists else "") + f":8790 served_by={(d or {}).get('served_by') if isinstance(d, dict) else None}"


def c_no_stale_tasks():
    cutoff = time.time() - STALE_HOURS * 3600
    try:
        with _db() as db:
            n = db.execute("select count(*) from durable_tasks where state in ('failed','needs_owner') and updated_at < ?", (cutoff,)).fetchone()[0]
    except Exception as e:  # noqa: BLE001
        return False, f"db error {e}"
    return n == 0, f"{n} failed/waiting tasks older than {STALE_HOURS}h"


def c_turn_success():
    cutoff = time.time() - 24 * 3600
    try:
        with _db() as db:
            rows = db.execute("select status, count(*) from client_requests where created_at > ? group by status", (cutoff,)).fetchall()
    except Exception as e:  # noqa: BLE001
        return False, f"db error {e}"
    counts = dict(rows)
    done = counts.get("completed", 0)
    total = sum(v for k, v in counts.items() if k != "cancelled")
    if total < 5:
        return True, f"only {total} turns in 24h (floor not applied); {counts}"
    rate = done / total
    return rate >= SUCCESS_FLOOR, f"{rate:.0%} of {total} turns in 24h (floor {SUCCESS_FLOOR:.0%}); {counts}"


def c_mac_control_tools():
    src = (REPO / "packages/jaeger-agent/jaeger_agent/tools/system_control.py").read_text()
    need = ["lock_screen", "display_off", "open_app", "quit_app", "status"]
    missing = [a for a in need if f'"{a}"' not in src]
    return not missing, f"missing actions: {missing}" if missing else "lock, display off, open/quit app, status"


def c_telegram_ready():
    """Telegram/iMessage are optional (Matthew uses web push): wiring present, off unless configured."""
    relay = REPO / "jaeger_ai/features/channels/relay/service.py"
    src = relay.read_text("utf-8") if relay.exists() else ""
    gated = 'self.cfg["telegram"].get("enabled", True)' in src and 'self.cfg["imessage"].get("enabled", True)' in src
    env = JAEGER / "secrets.env"
    has = env.exists() and any(l.split("=", 1)[0].strip() == "JAEGER_TELEGRAM_BOT_TOKEN" and l.split("=", 1)[1].strip()
                               for l in env.read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
    return gated, ("optional channels wired and gated; Telegram " + ("on (token present)" if has else "off (no token)")
                   if gated else "relay does not gate optional channels on their settings")


def c_push_device():
    p = JAEGER / "secrets" / "push_subscriptions.json"
    try:
        n = len(json.loads(p.read_text()))
    except Exception:
        n = 0
    return n > 0, f"{n} phone(s) subscribed"


def c_otel():
    hits = _grep(r"^\s*(from|import) opentelemetry", "jaeger_ai/core", "packages/jaeger-agent/jaeger_agent")
    spans = HOME / ".jaeger/logs/otel-spans.jsonl"
    live = 0
    if spans.exists():
        import time as _t
        cutoff = (_t.time() - 86400) * 1e9
        for line in spans.read_text(errors="ignore").splitlines()[-2000:]:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("name", "").startswith("invoke_agent") and (rec.get("start_ns") or 0) > cutoff:
                live += 1
    return bool(hits) and live > 0, f"{len(hits)} OTel imports; {live} invoke_agent spans in 24h ({spans})"


CUT = [
    "jaeger_ai/features/finance",
    "packages/jaeger-agent/jaeger_agent/delegates/openclaw", "jaeger_ai/plugins/voice_loop.py",
    "jaeger_ai/features/youtube_studio",
]
# C2/C3: approved by Matthew 2026-11-16 1:45 PM PST ("yes do whatever cuts u
# need"). Archived to the Desktop folder backlog-and-ares-muse-bridge/; the
# backlog routes and jaeger.backlog_* MCP tools must not come back.
CUT_BLOCKED = ["jaeger_ai/features/backlog", "jaeger_ai/features/agent_bridge/muse_file_bridge.py",
               "jaeger_ai/features/agent_bridge/ares_worker.py"]


def c_cut_list():
    left = [p for p in CUT if (REPO / p).exists()]
    return not left, f"still present: {left}" if left else "cut list cleared"


def c_cut_blocked():
    left = [p for p in CUT_BLOCKED if (REPO / p).exists()]
    wired = [f for f in ("jaeger_ai/features/agent_bridge/mcp.py", "jaeger_ai/core/gateway/server.py",
                         "jaeger_ai/core/gateway/caller_auth.py")
             if "/v1/backlog" in (REPO / f).read_text("utf-8") or "features.backlog" in (REPO / f).read_text("utf-8")]
    if left or wired:
        return False, f"still present: {left} wired: {wired}"
    return True, "archived (approved by Matthew 2026-11-16 1:45 PM PST); no backlog routes or MCP tools left"


C7_CUT = ("jaeger_ai/features/agentgateway", "jaeger_ai/features/goals",
          "jaeger_ai/features/oss_stack/routes.py", "jaeger_ai/features/oss_stack/router.py",
          "jaeger_ai/features/oss_stack/mcp_pool.py", "jaeger_ai/features/oss_stack/docs_indexer.py",
          "jaeger_ai/features/oss_stack/browser_proxy.py")


def c_c7_cut():
    left = [p for p in C7_CUT if (REPO / p).exists()]
    keep = [p for p in ("jaeger_ai/features/oss_stack/docs.py", "jaeger_ai/core/team") if not (REPO / p).exists()]
    wired = [f for f in ("jaeger_ai/core/gateway/server.py", "jaeger_ai/main.py", "jaeger_ai/features/agent_bridge/mcp.py",
                         "jaeger_ai/core/gateway/caller_auth.py")
             if any(t in (REPO / f).read_text("utf-8") for t in ("features.goals import", "oss_stack.routes",
                                                                 "features.agentgateway", "/v1/docs/search"))]
    if left or keep or wired:
        return False, f"still present: {left} missing keepers: {keep} wired: {wired}"
    return True, "agentgateway, goals, oss_stack routes archived (general cut approval 1:45 PM PST); docs.py + core/team kept"


def c_one_phone_relay():
    left = [p for p in ("jaeger_ai/plugins/telegram", "jaeger_ai/plugins/imessage", "jaeger_ai/plugins/discord") if (REPO / p).exists()]
    return not left, f"duplicate relays: {left}" if left else "features/channels only"


def c_one_launcher():
    extra = [str(p) for p in (HOME / "Applications/Jaeger.app", HOME / "Applications/Jaeger Desktop.app") if p.exists()]
    return not extra, f"extra launchers: {extra}" if extra else "JaegerAI.app only"


LIVE_LABELS = {"gateway", "bridge", "mcp-http", "voice", "channels", "droid", "logrotate"}


def c_no_stale_plists():
    d = HOME / ".jaeger/launchd"
    extra = sorted(p.name for p in d.glob("*.plist")
                   if p.name.removeprefix("com.jenkinsrobotics.jaeger-").removesuffix(".plist") not in LIVE_LABELS)
    return not extra, f"unused plists: {extra}" if extra else "only live service plists"


def c_no_second_checkout():
    src = HOME / ".jaeger/source"
    deploy = REPO / "scripts/deploy-live-mac-studio.sh"
    left = [str(p) for p in (src, deploy) if p.exists()]
    return not left, f"still present: {left}" if left else "services run from ~/GitHub/JaegerAI only"


def c_blocking_hooks():
    loop = (REPO / "packages/jaeger-agent/jaeger_agent/loop/jaeger_agent.py").read_text()
    hooks = (REPO / "packages/jaeger-agent/jaeger_agent/tool_executor.py").read_text()
    ok = "return HookedToolExecutor(" in loop and "blocked_by_hook" in hooks and "pre_tool_call" in hooks
    return ok, "pre_tool_call veto (shell hooks, exit 2 blocks) + in-process pre_tool hooks wrap every tool call" if ok else "hook executor not in the default chain"


def c_bridge_no_producers():
    src = (REPO / "jaeger_ai/interfaces/bridge.py").read_text()
    ok = 'JAEGER_BRIDGE_LOCAL_PRODUCERS", "").strip() == "1"' in src
    holder = ""
    lock = HOME / ".jaeger/instances/jaeger/run/background_producers.lock"
    try:
        out = subprocess.run(["lsof", "-t", str(lock)], capture_output=True, text=True, timeout=5).stdout.split()
        if out:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", out[0]], capture_output=True, text=True, timeout=5).stdout
            holder = "gateway" if "core.gateway.server" in cmd else cmd.strip()[:60]
    except Exception:
        pass
    ok = ok and holder in ("gateway", "")
    return ok, f"producer lease held by: {holder or 'nobody'}; bridge opt-in only"


def c_removed_index():
    if not REMOVED.exists():
        return True, "nothing removed yet"
    folders = [p for p in REMOVED.iterdir() if p.is_dir()]
    no_readme = [p.name for p in folders if not (p / "README.md").exists()]
    index = (REMOVED / "INDEX.md").read_text() if (REMOVED / "INDEX.md").exists() else ""
    unlisted = [p.name for p in folders if p.name not in index]
    ok = not no_readme and not unlisted
    return ok, f"{len(folders)} feature folders; missing README {no_readme or 'none'}; not in INDEX {unlisted or 'none'}"


# id, audit item, check, resolved?
CHECKS = [
    ("G01", "Gateway no longer calls itself openclaw-parity", c_no_openclaw_parity, True),
    ("G02", "Voice :8794 answers /health", c_voice_health, True),
    ("G03", "Gateway /health is green", c_gateway_health, True),
    ("G04", "Every Jaeger service launchd job is running", c_launchd_running, True),
    ("G05", "Boot stack-up job waits long enough (no exit 1 at boot)", c_stack_boot_wait, True),
    ("G06", "One turn path (gateway owner loop)", c_single_turn_path, True),
    ("G07", "One scheduler", c_one_scheduler, True),
    ("G08", "One heartbeat", c_one_heartbeat, True),
    ("G09", "No Hermes WebUI copy", c_no_hermes_webui, False),
    ("G10", "No stale failed/waiting tasks", c_no_stale_tasks, True),
    ("G11", "Turn success above floor", c_turn_success, False),
    ("G12", "Mac control actions", c_mac_control_tools, True),
    ("G13", "Optional Telegram/iMessage wired, off unless configured", c_telegram_ready, True),
    ("G14", "Phone push signed up", c_push_device, False),
    ("G15", "OpenTelemetry GenAI spans live", c_otel, True),
    ("G16", "Cut list cleared (finance, youtube_studio, openclaw delegate, voice_loop)", c_cut_list, True),
    ("G17", "One phone relay", c_one_phone_relay, True),
    ("G18", "One Mac launcher", c_one_launcher, True),
    ("G19", "Removed features archived with README + INDEX", c_removed_index, True),
    ("G20", "No unused launchd plists", c_no_stale_plists, True),
    ("G21", "No second deploy checkout", c_no_second_checkout, True),
    ("G22", "Cut list: backlog + ARES/Muse bridge parts", c_cut_blocked, True),
    ("G23", "Blocking pre-tool hooks in the default tool chain", c_blocking_hooks, True),
    ("G24", "Schedules/heartbeat/board run only in the Gateway (bridge never takes the lease)", c_bridge_no_producers, True),
    ("G25", "C7 cuts: agentgateway, goals, unused oss_stack routes", c_c7_cut, True),
]


def main() -> int:
    markdown = "--markdown" in sys.argv
    failed = 0
    rows = []
    for cid, name, fn, resolved in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error: {e}"
        state = "PASS" if ok else ("FAIL" if resolved else "OPEN")
        failed += state == "FAIL"
        rows.append((cid, state, name, detail))
    stamp = time.strftime("%Y-%m-%d %H:%M %Z")
    if markdown:
        print(f"Guard run {stamp}: {sum(r[1]=='PASS' for r in rows)} pass, {failed} fail, {sum(r[1]=='OPEN' for r in rows)} open\n")
        print("| Check | Result | Item | Detail |\n|---|---|---|---|")
        for r in rows:
            print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3].replace('|', '/')} |")
    else:
        for r in rows:
            print(f"{r[1]:<5} {r[0]} {r[2]} — {r[3]}")
        print(f"\n{stamp}: {failed} resolved check(s) failing")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
