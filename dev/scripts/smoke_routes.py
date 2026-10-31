#!/usr/bin/env python3
"""Route smoke suite for the unified UI (loopback only, GET only).

Enumerates routes from the code: the gateway aiohttp router (built against a temp store, never ~/.jaeger)
plus every literal /api|/v1 path in the WebUI dispatch modules, then GETs each against BASE
(default http://127.0.0.1:8790) and prints a table. Never sends bodies, cookies or tokens; never prints them.

  python dev/scripts/smoke_routes.py [--base URL] [--json] [--list]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
WEBUI_FILES = ["routes.py", "unified_api.py", "inbox_api.py", "widgets_api.py", "avatar_api.py",
               "jaeger_sessions.py", "jaeger_agents.py", "jaeger_gateway_routes.py", "remote_phone.py",
               "gateway_mirror.py", "request_diagnostics.py", "agent_health.py", "kanban_bridge.py"]
LIT = re.compile(r"""["'](/(?:api|v1)/[A-Za-z0-9_./{}:-]*[A-Za-z0-9_}])["']""")
# GETs that are not pure reads, or that stream / are long-poll: never hit against live.
UNSAFE = re.compile(
    r"(restart|shutdown|reboot|kill|delete|logout|login|stop|estop|cancel|/run$|init|settle|reset|reload|"
    r"inject_test|respond|/apply|/force|clear|/check$|refresh|/pull|/git/push|/fetch|/commit|/checkout|/stage|"
    r"/unstage|/discard|/stash|/start$|/new$|/create|/save|/move|/rename|/remove|/add$|/reorder|/revoke|/pair|"
    r"/install|/uninstall|/toggle|/set$|/switch|/write|/upload|/import|/generate|/chat|/btw|/steer|/exec|"
    r"/dispatch|/bulk|/tts$|/transcribe$|/escape|/terminal|/open-vscode|/reveal|/download|/cleanup|/archive|"
    r"/branch|/duplicate|/truncate|/undo|/retry|/compress|/repair|/restore|/share|/complete|/setup|/probe|"
    r"/authorize|/register|/options|/oidc|/csp-report|/client-events|/ack|-ack|/decide|/requests$|/actions$|"
    r"/change$|/capture|/preview$|/ai-edit|/update$|/pause|/resume|/yolo|/pin$|/regenerate|/anchor-scene|"
    r"/sidecar|/ws$|^/ws|/api/v1$|oauth|callback)", re.I)
STREAM = re.compile(r"(stream|/events$|sse|/watch|/live|/tail)", re.I)
PARAM = "smoke-missing"


def gateway_routes() -> set[str]:
    for sub in ("packages/jaeger-whisper-stt", "packages/jaeger-kokoro-tts", "packages/jaeger-agent", "packages/jaeger-os", "."):
        sys.path.insert(0, str(ROOT / sub))
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    with tempfile.TemporaryDirectory() as d:
        g = JaegerGatewayApp(store=GatewaySessionStore(Path(d) / "smoke.sqlite3"))
        out = set()
        for r in g.app.router.routes():
            if r.method in ("GET", "*") and r.resource is not None:
                out.add(r.resource.canonical)
        return out


def webui_routes() -> set[str]:
    out = set()
    for name in WEBUI_FILES:
        p = ROOT / "jaeger_ai/features/webui/api" / name
        if p.exists():
            out.update(m.group(1).rstrip("/.") for m in LIT.finditer(p.read_text()))
    return {r for r in out if r.count("/") >= 2 and not re.search(r"\{(qs|query|suffix)\}", r)}


def concrete(route: str) -> str:
    return re.sub(r"\{[^}]+\}", PARAM, route)


def classify(status: int | None, err: str | None, templated: bool) -> str:
    if err == "down":
        return "DOWN"
    if status is None:
        return "ERR"
    if 200 <= status < 300:
        return "OK"
    if status in (401, 403):
        return "AUTH"
    if status == 404:
        return "OK-404" if templated else "NOT-MOUNTED"
    if status in (400, 405, 409, 422, 503):
        return "OK-" + str(status)  # route exists, refuses GET or missing input/upstream
    if status >= 500:
        return "FAIL"
    return "OK-" + str(status)


def probe(base: str, path: str, timeout: float) -> tuple[int | None, str | None, int]:
    t = time.monotonic()
    req = urllib.request.Request(base + path, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(256)
            return r.status, None, int((time.monotonic() - t) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, None, int((time.monotonic() - t) * 1000)
    except (ConnectionRefusedError, urllib.error.URLError) as e:
        down = isinstance(getattr(e, "reason", e), ConnectionRefusedError) or isinstance(e, ConnectionRefusedError)
        return None, "down" if down else type(e).__name__, int((time.monotonic() - t) * 1000)
    except Exception as e:  # timeout etc.
        return None, type(e).__name__, int((time.monotonic() - t) * 1000)


def enumerate_routes() -> list[dict]:
    gw, wu = gateway_routes(), webui_routes()
    rows = []
    for r in sorted(gw | wu):
        skip = "unsafe" if UNSAFE.search(r) else "stream" if STREAM.search(r) else None
        rows.append({"route": r, "source": "+".join(s for s, set_ in (("gateway", gw), ("webui", wu)) if r in set_),
                     "skip": skip})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8790")
    ap.add_argument("--timeout", type=float, default=4.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if urlparse(a.base).hostname not in ("127.0.0.1", "localhost", "::1"):
        print("refusing: loopback only", file=sys.stderr)
        return 2
    rows = enumerate_routes()
    if a.list:
        print("\n".join(f'{r["route"]}\t{r["source"]}\t{r["skip"] or ""}' for r in rows))
        return 0
    for r in rows:
        if r["skip"]:
            r.update(status=None, result="SKIP-" + r["skip"], ms=0)
            continue
        st, err, ms = probe(a.base, concrete(r["route"]), a.timeout)
        r.update(status=st, result=classify(st, err, "{" in r["route"]), ms=ms, error=err)
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        w = max(len(r["route"]) for r in rows)
        print(f'{"ROUTE".ljust(w)}  {"SOURCE":13} {"STATUS":6} {"MS":>5}  RESULT')
        for r in rows:
            print(f'{r["route"].ljust(w)}  {r["source"]:13} {str(r["status"] or "-"):6} {r["ms"]:>5}  {r["result"]}')
        tally = {}
        for r in rows:
            k = r["result"].split("-")[0]
            tally[k] = tally.get(k, 0) + 1
        print("\nTOTAL", len(rows), " ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    return 1 if any(r["result"] in ("FAIL", "ERR") for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
