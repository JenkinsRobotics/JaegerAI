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
#: Outside-caller (MCP app / A2A) sessions and goals reuse the existing turn lifecycle
#: events; only rows whose session belongs to a caller are recorded (never Matthew's chats).
CALLER_KINDS = ("turn.start", "turn.finish", "turn.failed", "turn.cancelled", "turn.unknown")
_CALLER_STATUS = {"turn.start": "running", "turn.finish": "completed", "turn.failed": "failed",
                  "turn.cancelled": "cancelled", "turn.unknown": "execution_unknown"}
#: Agent-bridge inbox handoffs between apps (handoff_task to a peer, post_result back).
BRIDGE_KINDS = ("handoff.sent", "handoff.result")
#: Shared web search calls (POST /v1/search, /v1/fetch), attributed to the caller.
SEARCH_KINDS = ("search.query", "search.fetch", "model.route", "tool.call", "docs.search", "backlog.updated")
ALL_KINDS = KINDS + CALLER_KINDS + BRIDGE_KINDS + SEARCH_KINDS
MAX_ROWS = 50_000
MAX_LIMIT = 200


def ensure(conn: sqlite3.Connection) -> None:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_activity'").fetchone()
    conn.execute("CREATE TABLE IF NOT EXISTS agent_activity (event_id INTEGER PRIMARY KEY, ts REAL NOT NULL, "
                 "kind TEXT NOT NULL, agent_id TEXT, actor_id TEXT, session_id TEXT NOT NULL, "
                 "dedupe_key TEXT NOT NULL UNIQUE, data_json TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_activity_agent ON agent_activity(agent_id, event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_activity_actor ON agent_activity(actor_id, event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_activity_kind ON agent_activity(kind, event_id)")
    conn.execute("CREATE TABLE IF NOT EXISTS agent_activity_meta (key TEXT PRIMARY KEY, value TEXT)")
    backfill = KINDS if not exists else ()
    if not conn.execute("SELECT 1 FROM agent_activity_meta WHERE key='caller_backfill_v1'").fetchone():
        backfill = backfill + CALLER_KINDS
        conn.execute("INSERT OR IGNORE INTO agent_activity_meta VALUES ('caller_backfill_v1', '1')")
    if backfill:
        marks = ",".join("?" * len(backfill))
        for table in ("activity_history", "events"):
            try:
                rows = conn.execute(f"SELECT event_id, session_id, event, data_json, timestamp FROM {table} "
                                    f"WHERE event IN ({marks}) ORDER BY event_id", backfill).fetchall()
            except sqlite3.OperationalError:
                continue
            for r in rows:
                try:
                    data = json.loads(r[3] or "{}")
                except ValueError:
                    continue
                record(conn, int(r[0]), str(r[1]), str(r[2]), data, float(r[4]))


def _handoff(data: dict) -> dict:
    h = data.get("handoff")
    return h if isinstance(h, dict) else {}


def caller_of(session_id: str) -> tuple[str, str] | None:
    """(caller_id, caller_kind) for an outside caller's session (``codex:…``, ``agent:codex:…``), else None."""
    from jaeger_ai.core.gateway.caller_auth import CALLERS
    sid = str(session_id or "")
    for spec in CALLERS.values():
        if spec.session_prefix and sid.startswith(spec.session_prefix):
            return spec.name, ("a2a" if spec.actor == "a2a" else "mcp")
    if sid.startswith("agent:"):
        name = sid.split(":", 2)[1] if sid.count(":") >= 2 else ""
        spec = CALLERS.get(name)
        if spec is not None and spec.session_prefix:
            return spec.name, ("a2a" if spec.actor == "a2a" else "mcp")
    return None


def _caller_tag(conn: sqlite3.Connection, session_id: str, kind: str, data: dict) -> dict | None:
    who = caller_of(session_id)
    if who is None:
        return None
    tag = {"caller_id": who[0], "caller_kind": who[1], "session_id": session_id,
           "request_id": data.get("request_id"), "status": _CALLER_STATUS[kind]}
    try:
        g = conn.execute("SELECT id, thread FROM agent_goals WHERE request_id=?", (data.get("request_id"),)).fetchone()
    except sqlite3.OperationalError:  # bridge tables not created in this store
        g = None
    if g is not None:
        tag.update(goal_id=g[0], thread=g[1])
    try:
        meta = conn.execute("SELECT metadata_json FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        tag["agent_id"] = (json.loads(meta[0] or "{}") if meta else {}).get("agent_id")
    except (sqlite3.OperationalError, ValueError):
        pass
    return tag


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
    caller = data.get("caller") if isinstance(data.get("caller"), dict) else {}
    if kind in SEARCH_KINDS:
        refs.update(caller_id=caller.get("caller_id"), caller_kind=caller.get("caller_kind"), session_id=None)
        return {"agent_id": None, "actor_id": caller.get("caller_id"), "refs": refs, "entity": None}
    if kind in BRIDGE_KINDS:
        refs.update(handoff_id=data.get("handoff_id"), thread=data.get("thread"), message_id=data.get("message_id"),
                    caller_id=caller.get("caller_id"), caller_kind=caller.get("caller_kind"),
                    recipient=data.get("recipient"), session_id=None)
        return {"agent_id": data.get("recipient"), "actor_id": caller.get("caller_id"), "refs": refs,
                "entity": f"{caller.get('caller_id')}:{data.get('message_id')}" if data.get("message_id") else None}
    if kind in CALLER_KINDS and caller:
        refs.update(session_id=caller.get("session_id"), request_id=caller.get("request_id"),
                    goal_id=caller.get("goal_id"), thread=caller.get("thread"),
                    caller_id=caller.get("caller_id"), caller_kind=caller.get("caller_kind"))
        key = f"goal:{caller.get('caller_id')}:{caller.get('goal_id')}" if caller.get("goal_id") else f"request:{caller.get('request_id')}"
        return {"agent_id": caller.get("agent_id") or data.get("agent_id"), "actor_id": caller.get("caller_id"), "refs": refs,
                "entity": f"{key}:{caller.get('status')}" if caller.get("request_id") else None}
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
    if kind in CALLER_KINDS:
        tag = _caller_tag(conn, session_id, kind, data)
        if tag is None:
            return
        data = {**data, "caller": tag}
    elif kind not in KINDS and kind not in BRIDGE_KINDS and kind not in SEARCH_KINDS:
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
    caller = data.get("caller") if isinstance(data.get("caller"), dict) else None
    if kind in CALLER_KINDS and caller:
        what = f"goal {caller.get('goal_id')}" if caller.get("goal_id") else "session turn"
        text = f": {str(data.get('text') or '')[:120]}" if kind == "turn.start" and data.get("text") else ""
        return f"{caller.get('caller_id')} ({caller.get('caller_kind')}) {what} {caller.get('status')}{text}"
    if kind in SEARCH_KINDS:
        who = (data.get("caller") or {}).get("caller_id") if isinstance(data.get("caller"), dict) else None
        if kind == "model.route":
            why = f" ({data.get('reason')})" if data.get("reason") else ""
            err = f": {str(data.get('error'))[:120]}" if data.get("error") else ""
            return f"{who} model {data.get('model') or '?'} -> {data.get('target') or '?'} [{data.get('status')}]{why}{err}"
        if kind == "tool.call":
            return f"{who} tool {data.get('server')}.{data.get('tool')} [{data.get('status')}]"
        if kind == "backlog.updated":
            return f"{who} {data.get('action') or 'updated'} backlog task: {str(data.get('title') or '')[:120]} ({data.get('status')})"
        if kind == "docs.search":
            return f"{who} searched Documents: {str(data.get('query') or '')[:120]} ({data.get('results')} results)"
        if kind == "search.query":
            return f"{who} searched: {str(data.get('query') or '')[:120]} ({data.get('results')} results{', cached' if data.get('cached') else ''})"
        return f"{who} fetched {str(data.get('url') or '')[:160]}{' (cached)' if data.get('cached') else ''}"
    if kind in BRIDGE_KINDS:
        frm = (data.get("caller") or {}).get("caller_id") if isinstance(data.get("caller"), dict) else None
        title = f": {str(data.get('title') or '')[:120]}" if data.get("title") else ""
        if kind == "handoff.sent":
            return f"{frm} handed off {data.get('handoff_id')} to {data.get('recipient')}{title}"
        return f"{frm} posted result for {data.get('handoff_id')} to {data.get('recipient')} [{data.get('status')}]{title}"
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
