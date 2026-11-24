"""Agent catalog, handoff, project & knowledge SQLite store mixin (Wave 4A)."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from typing import Any

from jaeger_ai.core.gateway import agent_activity as _agent_activity
from jaeger_ai.core.gateway import handoff_outputs as _handoff_outputs

def _ss(name: str) -> Any:
    from .. import session_store as _mod
    return getattr(_mod, name)


def _row_meta(*args: Any, **kwargs: Any) -> Any:
    return _ss("_row_meta")(*args, **kwargs)


def input_fingerprint(*args: Any, **kwargs: Any) -> Any:
    return _ss("input_fingerprint")(*args, **kwargs)


class AgentStoreMixin:
    """Agent catalog, handoff, project and activity persistence methods."""

    def acknowledge_unknown(self, session_id: str, *, actor: str, request_id: str | None = None) -> list[dict[str, Any]]:
        """Owner acknowledgement of unknown outcomes: the request keeps ``execution_unknown`` (truth),
        gains an ``acknowledged`` receipt (``replayed: False``), and the session is idle again.
        Nothing is executed or replayed. Returns the durable ``turn.unknown.acknowledged`` events."""
        with self._immediate() as conn:
            events = self._acknowledge_unknown(conn, session_id, actor=actor, now=time.time(), request_id=request_id)
        self._emit(events)
        return events

    def _acknowledge_unknown(self, conn: sqlite3.Connection, session_id: str, *, actor: str, now: float,
                             request_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM client_requests WHERE session_id=? AND status='execution_unknown'"
        args: tuple[Any, ...] = (session_id,)
        if request_id:
            sql += " AND request_id=?"
            args += (request_id,)
        events: list[dict[str, Any]] = []
        for row in conn.execute(sql, args).fetchall():
            result = _row_meta(row["result_json"])
            if result.get("acknowledged"):
                continue
            ack = {"at": now, "by": actor, "replayed": False,
                   "note": "Outcome unknown; acknowledged without replay"}
            result = {**result, "acknowledged": ack}
            conn.execute("UPDATE client_requests SET result_json=?, updated_at=? WHERE request_id=?",
                         (json.dumps(result), now, row["request_id"]))
            events.append(self._insert_event(conn, session_id, "turn.unknown.acknowledged", {
                "request_id": row["request_id"], "turn_id": row["turn_id"], "status": "execution_unknown",
                "acknowledged": ack}, now))
        still = conn.execute("SELECT 1 FROM client_requests WHERE session_id=? AND status='execution_unknown' "
                             "AND json_extract(result_json,'$.acknowledged') IS NULL LIMIT 1", (session_id,)).fetchone()
        if not still:
            conn.execute("UPDATE sessions SET status='idle', updated_at=? WHERE session_id=? AND status='execution_unknown'",
                         (now, session_id))
        return events

    def agent_activity(self, **filters: Any) -> dict[str, Any]:
        """G1: newest-first agent activity across all sessions (``GET /v1/activity``)."""
        with self._immediate() as conn:
            return _agent_activity.query(conn, **filters)

    def save_handoff(self, record: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        if record.get("status") in _handoff_outputs.TERMINAL:  # G3 typed outputs, computed outside the write lock
            try:
                lookup = getattr(self, "task_lookup", None)
                result = dict(record.get("result") or record.get("result_json") or {})
                result["artifact_refs"] = _handoff_outputs.normalize({**record, "result": result}, task_exists=lookup)
                record = {**record, "result": result}
            except Exception:  # noqa: BLE001 - outputs never block the terminal write
                logging.getLogger(__name__).warning("artifact refs failed for %s", record.get("id"), exc_info=True)
        with self._immediate() as conn:
            prior = conn.execute("SELECT * FROM handoffs WHERE id=?", (record["id"],)).fetchone()
            if prior and prior["status"] in {"completed", "failed", "cancelled", "denied"}:
                return self._handoff_row(prior)
            metadata=dict(record.get('metadata') or {})
            if prior:
                previous=json.loads(prior['metadata_json'] or '{}')
                for key in ('cancel_requested','cancel_operation_id','cancel_requested_at','cancel_origin_request_id','cancelled_before_admission','parent_binding','parent_binding_state','caller_actor','bridge_origin','requested_model','model_choice'):
                    if key in previous:metadata[key]=previous[key]
            conn.execute(
                """
                INSERT INTO handoffs(
                    id, request_id, from_agent_id, to_agent_id, parent_run_id, child_run_id,
                    task, status, require_approval, approval_id, result_json, metadata_json,
                    created_at, updated_at, session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    session_id=COALESCE(handoffs.session_id, excluded.session_id),
                    status=excluded.status,
                    child_run_id=excluded.child_run_id,
                    result_json=excluded.result_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record["id"],
                    record.get("request_id") or record["id"],
                    record["from_agent_id"],
                    record["to_agent_id"],
                    record.get("parent_run_id"),
                    record.get("child_run_id"),
                    record["task"],
                    record["status"],
                    1 if record.get("require_approval") else 0,
                    record.get("approval_id"),
                    json.dumps(record.get("result") or record.get("result_json") or {}),
                    json.dumps(metadata),
                    record.get("created_at") or now,
                    now,
                    record.get("session_id"),
                ),
            )
        return self.get_handoff(record["id"]) or record

    def request_handoff_cancellation(self, handoff_id: str, operation_id: str, *, origin_request_id: str | None = None) -> dict[str, Any]:
        """Monotonic intent. Only prove cancellation when no child was admitted."""
        from jaeger_ai.contract.handoffs import child_request_id
        with self._immediate() as conn:
            row=conn.execute('SELECT * FROM handoffs WHERE id=?',(handoff_id,)).fetchone()
            if row is None:raise KeyError(handoff_id)
            if row['status'] in {'completed','failed','cancelled','denied','rejected'}:return self._handoff_row(row)
            meta=json.loads(row['metadata_json'] or '{}')
            if not meta.get('cancel_requested'):
                meta.update(cancel_requested=True,cancel_operation_id=operation_id,cancel_requested_at=time.time(),cancel_origin_request_id=origin_request_id)
            child=conn.execute('SELECT status FROM client_requests WHERE request_id=?',(child_request_id(row['request_id']),)).fetchone()
            status=row['status'];result=json.loads(row['result_json'] or '{}')
            if child is None and status in {'pending_approval','approved','admitted'}:
                status='cancelled';meta['cancelled_before_admission']=True
                result={'ok':False,'status':'cancelled','summary':'Cancelled before child admission; no child execution started','metadata':{'cancellation_confirmed':True,'confirmation_scope':'pre_admission'}}
            conn.execute('UPDATE handoffs SET metadata_json=?,status=?,result_json=?,updated_at=? WHERE id=?',(json.dumps(meta),status,json.dumps(result),time.time(),handoff_id))
            row=conn.execute('SELECT * FROM handoffs WHERE id=?',(handoff_id,)).fetchone()
            return self._handoff_row(row)

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
            return self._handoff_row(row) if row else None

    def get_handoff_by_request(self, request_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM handoffs WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._handoff_row(row) if row else None

    def mark_agent_seen(self, agent_id: str, *, seen_at: float, event_id: int | None = None, unread: bool = False) -> dict[str, Any]:
        record = {"agent_id": agent_id, "seen_at": float(seen_at), "event_id": event_id, "unread": unread}
        with self._immediate() as conn:
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"agent_seen:{agent_id}", json.dumps(record)),
            )
        return record

    def primary_agent_id(self) -> str:
        from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
        with self._immediate() as conn:
            conn.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('agent_primary:operator',?)", (json.dumps(LEAD_AGENT_ID),))
            return self._read_primary_agent(conn)

    @staticmethod
    def _read_primary_agent(conn) -> str:
        from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
        row = conn.execute("SELECT value FROM schema_meta WHERE key='agent_primary:operator'").fetchone()
        value = json.loads(row['value']) if row else LEAD_AGENT_ID
        if not isinstance(value, str) or not value:
            raise ValueError('Invalid operator primary pointer; preserved without overwriting')
        return value

    def set_primary_agent(self, agent_id: str, expected_id: str) -> None:
        if any(not isinstance(v, str) or not v for v in (agent_id, expected_id)):
            raise ValueError('Primary IDs must be nonempty strings')
        from jaeger_ai.core.gateway.agent_presentation import MAX_AGENT_PINS, PresentationConflict
        with self._immediate() as conn:
            if self._read_primary_agent(conn) != expected_id:
                raise PresentationConflict('Primary changed on another client; refresh and retry')
            data = self._read_agent_presentation(conn)
            prefs = data.setdefault(agent_id, {})
            if prefs.get('archived') or prefs.get('deleted'):
                raise PresentationConflict('Restore this agent before making it primary')
            if not prefs.get('pinned'):
                if sum(p.get('pinned') is True for p in data.values()) >= MAX_AGENT_PINS:
                    raise PresentationConflict('Pin slots are full; unpin an agent before replacing primary')
                prefs.update(pinned=True, pin_order=max((p.get('pin_order', -1) for p in data.values()), default=-1) + 1)
            self._write_agent_presentation(conn, data)
            conn.execute("INSERT INTO schema_meta(key,value) VALUES('agent_primary:operator',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(agent_id),))

    def agent_presentation(self) -> dict[str, dict[str, Any]]:
        with self._get_conn() as conn:
            return self._read_agent_presentation(conn)

    @staticmethod
    def _read_agent_presentation(conn) -> dict[str, dict[str, Any]]:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'agent_presentation:operator'").fetchone()
        data = json.loads(row["value"]) if row else {}
        if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
            raise ValueError("Invalid operator presentation metadata; preserved without overwriting")
        return data

    @staticmethod
    def _write_agent_presentation(conn, data) -> None:
        conn.execute("INSERT INTO schema_meta(key,value) VALUES('agent_presentation:operator',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(data),))

    @staticmethod
    def _read_agent_sections(conn) -> list[dict[str, Any]]:
        row = conn.execute("SELECT value FROM schema_meta WHERE key='agent_sections:operator'").fetchone()
        data = json.loads(row['value']) if row else []
        if not isinstance(data, list) or any(not isinstance(s, dict) or not isinstance(s.get('id'), str) or not isinstance(s.get('name'), str) for s in data):
            raise ValueError('Invalid section metadata; preserved without overwriting')
        return data

    def agent_sections(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            return self._read_agent_sections(conn)

    def create_agent_section(self, name: str) -> dict[str, Any]:
        from jaeger_ai.core.gateway.agent_presentation import validate_patch
        name = validate_patch({'display_name': name})['display_name']
        if name is None:
            raise ValueError('Section name required')
        with self._immediate() as conn:
            sections = self._read_agent_sections(conn)
            if len(sections) >= 32:
                raise ValueError('At most 32 sections')
            section = {'id': 'section_' + uuid.uuid4().hex, 'name': name, 'order': len(sections)}
            sections.append(section)
            conn.execute("INSERT INTO schema_meta(key,value) VALUES('agent_sections:operator',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(sections),))
            return section

    def patch_agent_presentation(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from jaeger_ai.core.gateway.agent_presentation import validate_patch, MAX_AGENT_PINS
        patch = validate_patch(body)
        with self._immediate() as conn:
            data = self._read_agent_presentation(conn)
            prefs = dict(data.get(agent_id, {}))
            if patch.get('deleted') is True and self._read_primary_agent(conn) == agent_id:
                raise ValueError('Replace the primary bot before deleting it')
            if patch.get('section_id') is not None and patch['section_id'] not in {s['id'] for s in self._read_agent_sections(conn)}:
                raise ValueError('Section not found')
            if patch.get('pinned') is True and not prefs.get('pinned'):
                if sum(v.get('pinned') is True for v in data.values()) >= MAX_AGENT_PINS:
                    raise ValueError(f'At most {MAX_AGENT_PINS} agents can be pinned; unpin an agent first')
                prefs['pin_order'] = max((v.get('pin_order', -1) for v in data.values()), default=-1) + 1
            for key, value in patch.items():
                if value is None:
                    prefs.pop(key, None)
                else:
                    prefs[key] = value
            if prefs.get('pinned') is False:
                prefs.pop('pin_order', None)
            data[agent_id] = prefs
            self._write_agent_presentation(conn, data)
            return prefs

    def set_agent_pins(self, ids: list[str], expected_ids: list[str]) -> None:
        from jaeger_ai.core.gateway.agent_presentation import MAX_AGENT_PINS, PresentationConflict
        if not isinstance(expected_ids, list) or any(not isinstance(i, str) for i in expected_ids) or len(set(expected_ids)) != len(expected_ids):
            raise ValueError("expected_agent_ids must be a unique list of agent IDs")
        if not isinstance(ids, list) or len(ids) > MAX_AGENT_PINS or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError(f'agent_ids must be a unique list of at most {MAX_AGENT_PINS} agent IDs')
        with self._immediate() as conn:
            data = self._read_agent_presentation(conn)
            current = sorted((key for key, prefs in data.items() if prefs.get('pinned') is True), key=lambda key: data[key].get('pin_order', 0))
            if current != expected_ids:
                raise PresentationConflict('Pins changed on another client; refresh and retry')
            for key, prefs in data.items():
                prefs['pinned'] = key in ids
                prefs.pop('pin_order', None)
            for index, agent_id in enumerate(ids):
                data.setdefault(agent_id, {}).update(pinned=True, pin_order=index)
            self._write_agent_presentation(conn, data)

    def agents_seen(self) -> dict[str, dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT value FROM schema_meta WHERE key LIKE 'agent_seen:%'").fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                record = json.loads(row["value"])
            except (TypeError, ValueError):
                continue
            out[str(record.get("agent_id"))] = record
        return out

    def list_handoffs(
        self,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        since: float | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Newest first. ``agent_id`` matches either end of the handoff."""
        sql = f"SELECT h.*, {self._HANDOFF_SESSION_SQL} AS resolved_session_id FROM handoffs h"
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id:
            clauses.append("(h.to_agent_id = ? OR h.from_agent_id = ?)")
            params.extend([agent_id, agent_id])
        if session_id:
            clauses.append(f"{self._HANDOFF_SESSION_SQL} = ?")
            params.append(session_id)
        if since is not None:
            clauses.append("h.updated_at > ?")
            params.append(float(since))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY h.created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._handoff_row(r) for r in rows]

    def count_active_handoffs(self, *, parent_run_id: str | None = None) -> int:
        with self._get_conn() as conn:
            if parent_run_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM handoffs WHERE parent_run_id=? "
                    "AND status IN ('pending_approval', 'approved', 'running', 'admitted')",
                    (parent_run_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM handoffs "
                    "WHERE status IN ('pending_approval', 'approved', 'running', 'admitted')"
                ).fetchone()
            return int(row["n"] if row else 0)

    def _handoff_row(self, row: sqlite3.Row) -> dict[str, Any]:
        keys = row.keys()
        result = json.loads(row["result_json"] or "{}")
        meta = _row_meta(row["metadata_json"])
        return {
            "id": row["id"],
            "request_id": row["request_id"],
            "from_agent_id": row["from_agent_id"],
            "to_agent_id": row["to_agent_id"],
            "parent_run_id": row["parent_run_id"],
            "child_run_id": row["child_run_id"],
            "task": row["task"],
            "status": row["status"],
            "require_approval": bool(row["require_approval"]),
            "approval_id": row["approval_id"],
            "result": result,
            "result_summary": result.get("summary"),
            "metadata": meta,
            "session_id": (row["resolved_session_id"] if "resolved_session_id" in keys
                           else row["session_id"] if "session_id" in keys else None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "task_id": meta.get("task_id"),  # G5
        } | {"check": _handoff_outputs.check_of({"id": row["id"], "status": row["status"],
                                                   "updated_at": row["updated_at"], "metadata": meta})}  # G2

    def set_handoff_check(self, handoff_id: str, check: dict[str, Any], *,
                          expected_state: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
        """G2: record an owner check on a terminal handoff (the only post-terminal metadata write).
        Returns (handoff, None) or (current_or_None, 'not_found'|'not_terminal'|'stale')."""
        with self._immediate() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
            if row is None:
                return None, "not_found"
            current = self._handoff_row(row)
            if row["status"] not in _handoff_outputs.TERMINAL:
                return current, "not_terminal"
            if expected_state is not None and current["check"]["state"] != expected_state:
                return current, "stale"
            meta = _row_meta(row["metadata_json"])
            meta["check"] = check
            conn.execute("UPDATE handoffs SET metadata_json=? WHERE id=?", (json.dumps(meta), handoff_id))
            return self._handoff_row(conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()), None

    def handoff_for_task(self, task_id: str) -> str | None:
        """G5: newest handoff linked to a task (join-on-read)."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT id FROM handoffs WHERE json_extract(metadata_json, '$.task_id')=? "
                               "ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
        return row[0] if row else None

    def append_handoff_post_once(self, session_id: str, role: str, text: str, *, kind: str, sender_agent_id: str | None, links: dict, meta: dict, parts=None) -> int:
        """Transcript delivery only; reuse the durable delivery receipt/transaction owner."""
        if kind not in {'handoff_request', 'handoff_result'} or not links.get('handoff_id'):
            raise ValueError('A handoff post requires its durable exchange ID')
        key = json.dumps(['handoff_post', links['handoff_id'], session_id, kind, meta.get('status')])
        with self._immediate() as conn:
            old = conn.execute('SELECT digest,receipt_json FROM background_deliveries WHERE delivery_key=?', (key,)).fetchone()
            digest = input_fingerprint(json.dumps({'role': role, 'text': text, 'sender': sender_agent_id, 'links': links, 'meta': meta}, sort_keys=True))
            if old:
                if old['digest'] != digest:
                    raise ValueError('Handoff post identity reused with different content')
                return json.loads(old['receipt_json'])['message_id']
            if not conn.execute('SELECT 1 FROM sessions WHERE session_id=?', (session_id,)).fetchone():
                raise ValueError('Original conversation unavailable')
            existing = conn.execute("SELECT id,content FROM messages WHERE session_id=? AND kind=? AND json_extract(links_json,'$.handoff_id')=? AND json_extract(meta_json,'$.status') IS ? ORDER BY id LIMIT 1", (session_id, kind, links['handoff_id'], meta.get('status'))).fetchone()
            if existing and existing['content'] != text:
                raise ValueError('Existing handoff post has different content; preserve it for reconciliation')
            mid = existing['id'] if existing else self.append_message(session_id, role, text, kind=kind, sender_agent_id=sender_agent_id, links=links, meta=meta, parts=parts, conn=conn)
            conn.execute('INSERT INTO background_deliveries(delivery_key,digest,receipt_json) VALUES(?,?,?)', (key, digest, json.dumps({'message_id': mid})))
            return mid

    def search_agent_messages(self, agent_id: str, query: str, *, before: int | None = None, limit: int = 20) -> dict[str, Any]:
        """Literal text search within the canonical agent's existing conversations.

        Stable message-ID cursor; no index/store copies, admission or read markers.
        Same metadata/legacy specialist binding as list_sessions(agent_id=...).
        """
        from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
        if not isinstance(query,str) or not 1<=len(query)<=200 or before is not None and (type(before) is not int or not 1<=before<2**63):
            raise ValueError('Invalid message search query/cursor')
        prefix = specialist_session(agent_id, '')
        where = "(json_extract(s.metadata_json, '$.agent_id') = ? OR (json_extract(s.metadata_json, '$.agent_id') IS NULL AND substr(s.session_id, 1, ?) = ?)) AND instr(unicode_casefold(m.content), unicode_casefold(?)) > 0"
        params: list[Any] = [agent_id, len(prefix), prefix, query]
        if before is not None:
            where += ' AND m.id < ?'
            params.append(before)
        with self._get_conn() as conn:
            conn.create_function('unicode_casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
            rows = conn.execute('SELECT m.id, m.session_id, m.role, m.kind, m.content, m.timestamp, s.title FROM messages m JOIN sessions s ON s.session_id=m.session_id WHERE ' + where + ' ORDER BY m.id DESC LIMIT ?', [*params, limit + 1]).fetchall()
        hits = []
        for row in rows[:limit]:
            content = str(row['content'] or '')
            folded_position = content.casefold().find(query.casefold())
            position, consumed = 0, 0
            for i, char in enumerate(content):
                if consumed + len(char.casefold()) > folded_position:
                    position = i
                    break
                consumed += len(char.casefold())
            start = max(0, position - 100)
            hits.append({'message_id': str(row['id']), 'session_id': row['session_id'], 'role': row['role'], 'kind': row['kind'], 'title': row['title'],
                         'timestamp': row['timestamp'], 'match_offset':position, 'content_revision':hashlib.sha256(content.encode()).hexdigest(), 'snippet': content[start:start + 500], 'content': content[:8000], 'truncated': len(content) > 8000})
        return {'agent_id': agent_id, 'matches': hits, 'next_before': str(rows[limit - 1]['id']) if len(rows) > limit else None, 'matching': 'literal_unicode_casefold'}

    def agent_message_content(self, agent_id: str, message_id: int, *, offset: int = 0, expected_revision: str | None = None) -> dict[str, Any] | None:
        """Bounded read of one exact agent-bound saved message; never selection/read mutation."""
        from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
        if type(message_id) is not int or not 1<=message_id<2**63 or type(offset) is not int or offset<0:
            raise ValueError('Invalid message identity/offset')
        prefix=specialist_session(agent_id,'')
        with self._get_conn() as conn:
            row=conn.execute("SELECT m.* FROM messages m JOIN sessions s ON s.session_id=m.session_id WHERE m.id=? AND (json_extract(s.metadata_json,'$.agent_id')=? OR (json_extract(s.metadata_json,'$.agent_id') IS NULL AND substr(s.session_id,1,?)=?))",(message_id,agent_id,len(prefix),prefix)).fetchone()
        if row is None:return None
        content=str(row['content'] or '')
        revision=hashlib.sha256(content.encode()).hexdigest()
        if expected_revision is not None and expected_revision!=revision:raise ValueError('Saved message revision changed; search again before reading it')
        if offset>len(content):raise ValueError('Message offset exceeds retained text')
        end=min(len(content),offset+8000)
        return {'agent_id':agent_id,'message_id':str(message_id),'session_id':row['session_id'],
                'role':row['role'],'kind':row['kind'],'content':content[offset:end],
                'offset':offset,'end_offset':end,'total_chars':len(content),'revision':revision,
                'next_offset':end if end<len(content) else None,'previous_offset':max(0,offset-8000) if offset else None}
