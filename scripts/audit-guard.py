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


SERVICE_JOBS = ["gateway", "webui", "bridge", "mcp-http", "voice", "channels", "droid"]


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
    legacy = _grep(r"^\s*def (_run_turn|run_for_voice|dispatcher_turn|jaeger_turn)\(", "jaeger_ai")
    return not legacy, ", ".join(legacy) or "only the gateway owner loop runs turns"


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
    return not exists, "features/webui present" if exists else "Gateway serves the UI"


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
    env = JAEGER / "secrets.env"
    has = env.exists() and any(l.split("=", 1)[0].strip() == "JAEGER_TELEGRAM_BOT_TOKEN" and l.split("=", 1)[1].strip()
                               for l in env.read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
    return has, "token present" if has else "no JAEGER_TELEGRAM_BOT_TOKEN in ~/.jaeger/secrets.env"


def c_push_device():
    p = JAEGER / "secrets" / "push_subscriptions.json"
    try:
        n = len(json.loads(p.read_text()))
    except Exception:
        n = 0
    return n > 0, f"{n} phone(s) subscribed"


def c_otel():
    hits = _grep(r"^\s*(from|import) opentelemetry", "jaeger_ai/core", "packages/jaeger-agent/jaeger_agent")
    return bool(hits), f"{len(hits)} OTel references in runtime"


CUT = [
    "jaeger_ai/features/finance", "jaeger_ai/features/backlog", "jaeger_ai/features/agent_bridge",
    "packages/jaeger-agent/jaeger_agent/delegates/openclaw", "jaeger_ai/plugins/voice_loop.py",
    "jaeger_ai/features/youtube_studio",
]


def c_cut_list():
    left = [p for p in CUT if (REPO / p).exists()]
    return not left, f"still present: {left}" if left else "cut list cleared"


def c_one_phone_relay():
    left = [p for p in ("jaeger_ai/plugins/telegram", "jaeger_ai/plugins/imessage", "jaeger_ai/plugins/discord") if (REPO / p).exists()]
    return not left, f"duplicate relays: {left}" if left else "features/channels only"


def c_one_launcher():
    extra = [str(p) for p in (HOME / "Applications/Jaeger.app", HOME / "Applications/Jaeger Desktop.app") if p.exists()]
    return not extra, f"extra launchers: {extra}" if extra else "JaegerAI.app only"


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
    ("G06", "One turn path (gateway owner loop)", c_single_turn_path, False),
    ("G07", "One scheduler", c_one_scheduler, True),
    ("G08", "One heartbeat", c_one_heartbeat, True),
    ("G09", "No Hermes WebUI copy", c_no_hermes_webui, False),
    ("G10", "No stale failed/waiting tasks", c_no_stale_tasks, True),
    ("G11", "Turn success above floor", c_turn_success, False),
    ("G12", "Mac control actions", c_mac_control_tools, True),
    ("G13", "Telegram token configured", c_telegram_ready, False),
    ("G14", "Phone push signed up", c_push_device, False),
    ("G15", "OpenTelemetry in runtime", c_otel, False),
    ("G16", "Cut list cleared", c_cut_list, False),
    ("G17", "One phone relay", c_one_phone_relay, False),
    ("G18", "One Mac launcher", c_one_launcher, False),
    ("G19", "Removed features archived with README + INDEX", c_removed_index, True),
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
