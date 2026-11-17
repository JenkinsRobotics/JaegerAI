"""Saved facts (the `remember` store) — readable and forgettable from Settings → Memory (R7).

The agent's `remember`/`recall`/`forget` tools and this view share one table
(`memory/state.db` → `facts`). Benchmark-sourced rows are never shown. Values
that look like credentials are masked; the owner can still forget them.
"""
from __future__ import annotations

import re
import sqlite3

from aiohttp import web

_SECRET = re.compile(r"pass(word|code)?|secret|token|api[_ -]?key|otp|pin\b|credential", re.I)


def register(gateway) -> None:
    from jaeger_ai.core.instance.instance import InstanceLayout

    def db_path():
        return InstanceLayout(root=gateway._instance_root()).root / "memory" / "state.db"

    def connect(write: bool = False):
        path = db_path()
        if not path.exists():
            raise FileNotFoundError("memory store not found")
        uri = f"file:{path}?mode={'rw' if write else 'ro'}"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    async def list_facts(request):
        q = (request.query.get("q") or "").strip().lower()
        try:
            with connect() as conn:
                rows = conn.execute(
                    "SELECT subject,key,value,category,source,updated_at FROM facts "
                    "WHERE source != 'benchmark' ORDER BY updated_at DESC LIMIT 1000").fetchall()
        except (FileNotFoundError, sqlite3.Error) as exc:
            return web.json_response({"facts": [], "count": 0, "error": str(exc)})
        out = []
        for r in rows:
            item = dict(r)
            if q and q not in " ".join(str(v or "") for v in item.values()).lower():
                continue
            if _SECRET.search(f"{item['key']} {item.get('category') or ''}"):
                item["value"], item["masked"] = "••••••", True
            out.append(item)
        return web.json_response({"facts": out, "count": len(out), "store": "memory/state.db (facts)"})

    async def forget_fact(request):
        try:
            body = await request.json()
            key, subject = str(body.get("key") or ""), str(body.get("subject") or "user")
            if not key:
                raise ValueError("key required")
        except (ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        try:
            with connect(write=True) as conn:
                n = conn.execute("DELETE FROM facts WHERE subject=? AND key=? AND source != 'benchmark'",
                                 (subject, key)).rowcount
                if n:
                    from datetime import datetime, timezone
                    conn.execute("INSERT INTO fact_log (subject,key,value,category,source,tags,note,ts) "
                                 "VALUES (?,?,'','forgotten','user','','forgotten',?)",
                                 (subject, key, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        except (FileNotFoundError, sqlite3.Error) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)
        gateway.event_bus.publish("*", "memory.changed", {"origin": "owner", "forgot": key})
        return web.json_response({"ok": True, "forgot": bool(n), "key": key, "subject": subject,
                                  "note": "History in fact_log is kept."})

    gateway.app.router.add_get("/v1/memory/facts", list_facts)
    gateway.app.router.add_post("/v1/memory/facts/forget", forget_fact)
