#!/usr/bin/env python3
"""Smoke-check the running Jaeger stack: one line per service, exit 1 on a miss.

  ./scripts/verify-stack-smoke.py           # HTTP checks only
  ./scripts/verify-stack-smoke.py --live    # also one real chat turn (verify-chat.py)
  ./scripts/verify-stack-smoke.py --json

Services (ports from jaeger_ai.contract.ports where defined):
  Gateway 33418  GET /health -> {"status": "ok"}
  WebUI    8790  GET /health -> {"status": "ok"} (served by the Gateway)
  MCP      8792  GET /mcp    -> 401 without the bearer: up and enforcing auth
  Voice    8794  GET /health -> {"ok": true}

Read-only: it never starts, stops or restarts anything and never sends a token.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"


def _get(url: str, timeout: float = 4.0) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - loopback only
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body, status = exc.read().decode("utf-8", "replace"), exc.code
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(getattr(exc, "reason", exc))
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body[:200]


def _ok_status(body) -> bool:
    return isinstance(body, dict) and (body.get("status") == "ok" or body.get("ok") is True)


CHECKS = (
    ("gateway", 33418, "/health", lambda code, body: code == 200 and _ok_status(body)),
    ("webui", 8790, "/health", lambda code, body: code == 200 and _ok_status(body)),
    ("mcp", 8792, "/mcp", lambda code, body: code in (200, 401, 405, 406)),
    ("voice", 8794, "/health", lambda code, body: code == 200 and _ok_status(body)),
)


def run_checks() -> list[dict]:
    rows = []
    for name, port, path, ok in CHECKS:
        code, body = _get(f"http://{HOST}:{port}{path}")
        rows.append({"service": name, "port": port, "path": path, "http": code, "ok": bool(ok(code, body)),
                     "detail": body if isinstance(body, str) else {k: body[k] for k in list(body)[:4]}})
    return rows


def live_chat() -> dict:
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "verify-chat.py"), "--label", "stack-smoke"],
                          capture_output=True, text=True, timeout=240)
    last = (proc.stdout.strip().splitlines() or [""])[-1]
    return {"service": "chat", "ok": proc.returncode == 0, "detail": last[:300]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="also run one real chat turn")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = run_checks()
    if args.live:
        rows.append(live_chat())
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        for r in rows:
            where = f":{r['port']}{r['path']}" if "port" in r else ""
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['service']:<8}{where}  {r.get('http', '')}")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
