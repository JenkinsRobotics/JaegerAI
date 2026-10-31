"""G1: durable, paged activity history for the Agents tab (``GET /v1/activity``).

One row per meaningful agent event, written in the same transaction as the
event itself (``SessionStore._insert_event``), so it survives the bounded SSE
replay window and restarts. The global and origin-chat copies of one event
collapse to one row through ``dedupe_key``. The table is created lazily with
``CREATE TABLE IF NOT EXISTS`` (no schema-version bump) and backfilled once
from the existing durable ``activity_history`` and ``events`` tables.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

KINDS = ("agent.handoff", "agent.handoff.finished", "agent.handoff.checked", "agent.status.changed",
         "agent.updated", "task.created", "task.updated", "approval.request", "approval.resolved",
         "project.checked")
MAX_ROWS = 50_000
MAX_LIMIT = 200
_ready: set[int] = set()


def ensure(conn: sqlite3.Connection) -> None:
    key = id(conn)
    if key in _ready:
        return
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_activity'").fetchone()
    conn.execute("CREATE TABLE IF NOT EXISTS agent_activity (event_id INTEGER PRIMARY KEY, ts REAL NOT NULL, "
                 "kind TEXT NOT NULL, agent_id TEXT, actor_id TEXT, session_id TEXT NOT NULL, "
                 "dedupe_key TEXT NOT NULL UNIQUE, data_json TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_activity_agent ON agent_activity(agent_id, event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_activity_actor ON agent_activity(actor_id, event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_activity_kind ON agent_activity(kind, event_id)")
    if not exists:
        marks = ",".join("?" * len(KINDS))
        for table in ("activity_history", "events"):
            try:
                rows = conn.execute(f"SELECT event_id, session_id, event, data_json, timestamp FROM {table} "
                                    f"WHERE event IN ({marks}) ORDER BY event_id", KINDS).fetchall()
            except sqlite3.OperationalError:
                continue
            for r in rows:
                try:
                    data = json.loads(r[3] or "{}")
                except ValueError:
                    continue
                record(conn, int(r[0]), str(r[1]), str(r[2]), data, float(r[4]))
    _ready.add(key)


def _handoff(data: dict) -> dict:
    h = data.get("handoff")
    return h if isinstance(h, dict) else {}


def classify(kind: str, data: dict) -> dict[str, Any]:
    """agent/actor ids, entity refs and a dedupe key for one event payload."""
    h = _handoff(data)
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    origin = data.get("origin") if isinstance(data.get("origin"), dict) else {}
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    refs = {"handoff_id": h.get("id") or data.get("handoff_id"),
            "task_id": task.get("task_id") or h.get("task_id") or (h.get("metadata") or {}).get("task_id")
            or data.get("task_id") or meta.get("task_id") or origin.get("task_id"),
            "approval_id": data.get("approval_id"),
            "project_id": data.get("project_id"),
            "session_id": (h.get("result") or {}).get("worker_session_id") or data.get("session_id")}
    agent = actor = None
    if h:
        agent, actor = h.get("to_agent_id"), h.get("from_agent_id")
    elif task:
        agent = task.get("agent_id") or task.get("owning_agent")
    elif kind.startswith("approval."):
        agent = origin.get("agent_id") or meta.get("agent_id") or data.get("agent_id")
    else:
        agent = data.get("agent_id") or data.get("primary_agent_id")
    if kind.startswith("agent.handoff"):
        state = h.get("status")
        if kind == "agent.handoff.checked":
            state = f"{state}:{(h.get('check') or {}).get('state')}:{(h.get('check') or {}).get('checked_at')}"
        entity = f"handoff:{refs['handoff_id']}:{state}"
    elif kind.startswith("task."):
        entity = f"task:{refs['task_id']}:{task.get('state')}:{task.get('updated_at')}"
    elif kind.startswith("approval.") and refs["approval_id"]:
        entity = f"approval:{refs['approval_id']}"
    elif kind == "project.checked":
        res = data.get("result") if isinstance(data.get("result"), dict) else {}
        agent = res.get("agent_id") or res.get("checked_by")
        entity = None  # every check run is its own row
    elif kind == "agent.status.changed":
        entity = f"status:{agent}:{data.get('status')}:{data.get('at')}"
    else:
        entity = None
    return {"agent_id": agent, "actor_id": actor, "refs": refs, "entity": entity}


def record(conn: sqlite3.Connection, event_id: int, session_id: str, kind: str, data: dict, ts: float) -> None:
    if kind not in KINDS:
        return
    c = classify(kind, data)
    dedupe = f"{kind}|{c['entity']}" if c["entity"] else f"{kind}|#{event_id}"
    cur = conn.execute("INSERT OR IGNORE INTO agent_activity VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (event_id, ts, kind, c["agent_id"], c["actor_id"], session_id, dedupe, json.dumps(data)))
    if cur.rowcount == 0 and session_id == "*":
        # The UI dedupes on the global live stream's event_id: the "*" copy wins
        # over an origin-session copy of the same event, whichever was written first.
        conn.execute("UPDATE agent_activity SET event_id=?, session_id='*', ts=?, data_json=? "
                     "WHERE dedupe_key=? AND session_id<>'*'", (event_id, ts, json.dumps(data), dedupe))
    if event_id % 500 == 0:
        conn.execute("DELETE FROM agent_activity WHERE event_id <= (SELECT event_id FROM agent_activity "
                     "ORDER BY event_id DESC LIMIT 1 OFFSET ?)", (MAX_ROWS,))


def _summary(kind: str, data: dict) -> str:
    h = _handoff(data)
    if h:
        who = h.get("to_agent_id") or "?"
        if kind == "agent.handoff":
            return f"{h.get('from_agent_id')} handed off to {who}: {str(h.get('task') or '')[:120]} [{h.get('status')}]"
        if kind == "agent.handoff.finished":
            return f"{who} {h.get('status')}: {str((h.get('result') or {}).get('summary') or h.get('task') or '')[:120]}"
        return f"check {(h.get('check') or {}).get('state')} for {who}"
    if kind.startswith("task."):
        t = data.get("task") or {}
        return f"task {t.get('state')}: {str(t.get('goal') or '')[:120]}"
    if kind == "approval.request":
        return f"asked approval: {str(data.get('prompt') or '')[:120]}"
    if kind == "approval.resolved":
        return f"approval {'granted' if data.get('approved') else 'declined'}"
    if kind == "project.checked":
        res = data.get("result") if isinstance(data.get("result"), dict) else {}
        state = res.get("status") or ("passed" if res.get("ok") is True else "failed" if res.get("ok") is False else "checked")
        return f"project {data.get('project_id')} check {state}"
    if kind == "agent.status.changed":
        return f"{data.get('previous')} → {data.get('status')}"
    return kind


def query(conn: sqlite3.Connection, *, before: int | None = None, since: float | None = None,
          agent_id: str | None = None, kinds: list[str] | None = None, needs_me: bool = False,
          limit: int = 50, pending_approvals: set[str] | None = None) -> dict[str, Any]:
    ensure(conn)
    limit = max(1, min(int(limit), MAX_LIMIT))
    sql, args = "SELECT * FROM agent_activity WHERE 1=1", []
    if before is not None:
        sql += " AND event_id < ?"; args.append(int(before))
    if since is not None:
        sql += " AND ts > ?"; args.append(float(since))
    if agent_id:
        sql += " AND (agent_id = ? OR actor_id = ?)"; args += [agent_id, agent_id]
    if needs_me:
        kinds = ["approval.request"]
    if kinds:
        parts = []
        for k in kinds:
            if k.endswith("*"):
                parts.append("kind LIKE ?"); args.append(k[:-1].replace("%", "") + "%")
            else:
                parts.append("kind = ?"); args.append(k)
        sql += " AND (" + " OR ".join(parts) + ")"
    sql += " ORDER BY event_id DESC LIMIT ?"
    args.append(limit * 4 + 1 if needs_me else limit + 1)
    rows = conn.execute(sql, args).fetchall()
    items = []
    for r in rows:
        data = json.loads(r["data_json"])
        c = classify(r["kind"], data)
        nm = r["kind"] == "approval.request" and (pending_approvals is None or c["refs"]["approval_id"] in pending_approvals)
        if needs_me and not nm:
            continue
        items.append({"event_id": r["event_id"], "kind": r["kind"], "ts": r["ts"], "agent_id": r["agent_id"],
                      "actor_id": r["actor_id"], "session_id": r["session_id"], "summary": _summary(r["kind"], data),
                      "needs_me": nm, "refs": c["refs"], "data": data})
    has_more = len(items) > limit or len(rows) > (limit * 4 if needs_me else limit)
    items = items[:limit]
    return {"items": items, "has_more": has_more, "next_before": items[-1]["event_id"] if items else before}
