"""Sessions, messages, topics, branching & read-state SQLite store mixin (Wave 4A)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any

def _ss(name: str) -> Any:
    from .. import session_store as _mod
    return getattr(_mod, name)


def _row_meta(*args: Any, **kwargs: Any) -> Any:
    return _ss("_row_meta")(*args, **kwargs)


def _list_preview(*args: Any, **kwargs: Any) -> Any:
    return _ss("_list_preview")(*args, **kwargs)


def _message_read_state(*args: Any, **kwargs: Any) -> Any:
    return _ss("_message_read_state")(*args, **kwargs)


def _session_agent(*args: Any, **kwargs: Any) -> Any:
    return _ss("_session_agent")(*args, **kwargs)


def _typed_fields(*args: Any, **kwargs: Any) -> Any:
    return _ss("_typed_fields")(*args, **kwargs)


def input_fingerprint(*args: Any, **kwargs: Any) -> Any:
    return _ss("input_fingerprint")(*args, **kwargs)


def is_generic_session_title(*args: Any, **kwargs: Any) -> Any:
    return _ss("is_generic_session_title")(*args, **kwargs)


def message_dict(*args: Any, **kwargs: Any) -> Any:
    return _ss("message_dict")(*args, **kwargs)


def title_from_user_text(*args: Any, **kwargs: Any) -> Any:
    return _ss("title_from_user_text")(*args, **kwargs)


class SessionDomainStoreMixin:
    """Sessions, messages, topics, branching, feedback and read-state methods."""

    def _ensure_title_source(self, conn: sqlite3.Connection) -> None:
        """Add sessions.title_source (auto/user) without bumping a skewed schema version."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "title_source" not in columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN title_source TEXT NOT NULL DEFAULT 'auto'")
        rows = conn.execute("SELECT session_id, metadata_json, title_source FROM sessions").fetchall()
        for row in rows:
            meta = _row_meta(row["metadata_json"])
            org = meta.get("chat_organization") if isinstance(meta.get("chat_organization"), dict) else {}
            source = row["title_source"] if row["title_source"] in {"auto", "user"} else None
            if source is None:
                source = org.get("title_source") if org.get("title_source") in {"auto", "user"} else (
                    "user" if org.get("manual_title") else "auto"
                )
            if org.get("title_source") != source or bool(org.get("manual_title")) != (source == "user") or row["title_source"] != source:
                org = dict(org)
                org["title_source"] = source
                org["manual_title"] = source == "user"
                meta["chat_organization"] = org
                conn.execute(
                    "UPDATE sessions SET title_source=?, metadata_json=? WHERE session_id=?",
                    (source, json.dumps(meta), row["session_id"]),
                )

    def _ensure_session_topics(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS session_topics (
                topic_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                title_source TEXT NOT NULL DEFAULT 'auto',
                start_message_id INTEGER NOT NULL,
                end_message_id INTEGER,
                summary TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_topics_session ON session_topics(session_id, start_message_id);
        """)

    def _title_source_of(self, row: sqlite3.Row, meta: dict[str, Any] | None = None) -> str:
        meta = meta if meta is not None else _row_meta(row["metadata_json"] if "metadata_json" in row.keys() else "{}")
        if "title_source" in row.keys() and row["title_source"] in {"auto", "user"}:
            return row["title_source"]
        org = meta.get("chat_organization") if isinstance(meta.get("chat_organization"), dict) else {}
        if org.get("title_source") in {"auto", "user"}:
            return org["title_source"]
        return "user" if org.get("manual_title") else "auto"

    def operator_state(self, key: str) -> dict[str, Any] | None:
        """Read one Gateway-owned operator projection."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value_json, revision, updated_at, updated_by FROM operator_state WHERE key=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        value = _row_meta(row["value_json"])
        return {
            **value,
            "revision": int(row["revision"]),
            "updated_at": float(row["updated_at"]),
            "updated_by": row["updated_by"],
        }

    def save_operator_state(
        self,
        key: str,
        value: dict[str, Any],
        *,
        actor: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Compare-and-set one operator projection and return its receipt."""
        now = time.time()
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT revision FROM operator_state WHERE key=?", (key,),
            ).fetchone()
            revision = int(row["revision"]) if row else 0
            if expected_revision is not None and int(expected_revision) != revision:
                raise _ss('StateConflict')(
                    f"operator state changed; expected revision {expected_revision}, current revision {revision}"
                )
            next_revision = revision + 1
            conn.execute(
                "INSERT INTO operator_state(key,value_json,revision,updated_at,updated_by) "
                "VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "value_json=excluded.value_json, revision=excluded.revision, "
                "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (key, json.dumps(value, sort_keys=True), next_revision, now, actor),
            )
        return {
            **value,
            "revision": next_revision,
            "updated_at": now,
            "updated_by": actor,
        }

    def active_session_state(self) -> dict[str, Any]:
        """The active owner conversation shared by every client device."""
        return self.operator_state("active_session") or {
            "active_session_id": None,
            "surface": None,
            "revision": 0,
            "updated_at": None,
            "updated_by": None,
        }

    def save_active_session(
        self,
        session_id: str | None,
        *,
        actor: str,
        surface: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Select one durable owner conversation, or clear the selection."""
        if session_id is not None and self.get_session(session_id) is None:
            raise ValueError("Session not found")
        return self.save_operator_state(
            "active_session",
            {"active_session_id": session_id, "surface": surface},
            actor=actor,
            expected_revision=expected_revision,
        )

    def list_sessions(self, profile: str | None = None, query: str | None = None,
                      agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            sql = (
                "SELECT s.*, COUNT(m.id) as message_count, MAX(m.timestamp) AS last_message_at, "
                "(SELECT lm.content FROM messages lm WHERE lm.session_id = s.session_id "
                " ORDER BY lm.timestamp DESC, lm.id DESC LIMIT 1) AS last_content, "
                "(SELECT MAX(e.event_id) FROM events e WHERE e.session_id = s.session_id) AS last_event_id "
                "FROM sessions s LEFT JOIN messages m ON s.session_id = m.session_id"
            )
            params: list[Any] = []
            clauses = []
            if profile:
                clauses.append("s.profile = ?")
                params.append(profile)
            if agent_id:
                from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
                prefix = specialist_session(agent_id, "")
                clauses.append("(json_extract(s.metadata_json, '$.agent_id') = ? "
                               "OR (json_extract(s.metadata_json, '$.agent_id') IS NULL "
                               "AND substr(s.session_id, 1, ?) = ?))")
                params.extend([agent_id, len(prefix), prefix])
            term = str(query or "").strip()
            if term:
                like = f"%{term}%"
                clauses.append("(s.title LIKE ? OR s.workspace LIKE ? OR s.session_id LIKE ? OR EXISTS (SELECT 1 FROM messages sm WHERE sm.session_id = s.session_id AND sm.content LIKE ?))")
                params.extend([like, like, like, like])
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " GROUP BY s.session_id ORDER BY s.updated_at DESC"
            rows = conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                meta = _row_meta(r["metadata_json"])
                row = {
                    "session_id": r["session_id"],
                    "title": r["title"],
                    "title_source": self._title_source_of(r, meta),
                    "profile": r["profile"],
                    "workspace": r["workspace"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "status": r["status"],
                    "message_count": r["message_count"],
                    "metadata": meta,
                    "unread": _message_read_state(meta)["unread"],
                    "archived": bool(meta.get("archived")),
                    "agent_id": _session_agent(r["session_id"], meta),
                    # Sidebar row without N follow-up reads (Agents View).
                    "last_message_preview": _list_preview(r["last_content"]),
                    "last_activity_at": max(float(r["updated_at"] or 0), float(r["last_message_at"] or 0)),
                    "last_event_id": r["last_event_id"],
                }
                if term:
                    row["search_match"] = True
                out.append(row)
            return out

    def backfill_generic_titles(self) -> int:
        """Give existing generic-titled conversations a title from the first user message.

        Does not mark titles as manual, so later edits still follow auto-title rules.
        Empty conversations are left unchanged.
        """
        changed = 0
        with self._immediate() as conn:
            rows = conn.execute("SELECT session_id, title, metadata_json FROM sessions").fetchall()
            for row in rows:
                if not is_generic_session_title(row["title"], _row_meta(row["metadata_json"])):
                    continue
                first = conn.execute(
                    "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                    "AND (kind IS NULL OR kind IN ('', 'message')) AND trim(content) != '' "
                    "ORDER BY timestamp ASC, id ASC LIMIT 1",
                    (row["session_id"],),
                ).fetchone()
                if first is None:
                    continue
                auto_title = title_from_user_text(first["content"])
                if auto_title:
                    conn.execute("UPDATE sessions SET title = ? WHERE session_id = ?",
                                 (auto_title, row["session_id"]))
                    changed += 1
        return changed

    def recover_interrupted_sessions(self) -> int:
        """A new gateway cannot attest completion of work its predecessor sent."""
        now = time.time()
        with self._immediate() as conn:
            changed = conn.execute(
                "UPDATE sessions SET status='execution_unknown', updated_at=? WHERE status IN ('running', 'cancelling')",
                (now,),
            )
            # Owner-invisible maintenance passes (skill/memory review) interrupted
            # by a restart are cancelled, not "unknown": nobody waits on them and
            # the next qualifying turn queues a fresh review (G11 / P21).
            conn.execute(
                "UPDATE client_requests SET status='cancelled', updated_at=? "
                "WHERE status IN ('admitted', 'running', 'cancelling', 'awaiting_approval') "
                "AND (request_id LIKE 'skill-review-%' OR request_id LIKE 'memory-review-%')",
                (now,),
            )
            conn.execute(
                "UPDATE client_requests SET status='execution_unknown', updated_at=? "
                "WHERE status IN ('admitted', 'running', 'cancelling', 'awaiting_approval')",
                (now,),
            )
            conn.execute(
                "UPDATE handoffs SET status='execution_unknown', updated_at=? "
                "WHERE status IN ('running', 'approved', 'admitted')",
                (now,),
            )
            return changed.rowcount

    def get_session(self, session_id: str, *, conversation: bool = False) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            if conversation:
                conn.execute("BEGIN")  # one read snapshot: transcript, receipt and replay cursor
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            messages = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? AND " + _ss('_HIDDEN_SQL') +
                " ORDER BY timestamp ASC, id ASC",
                (session_id,),
            ).fetchall()
            meta = _row_meta(row["metadata_json"])
            payload = {
                "session_id": row["session_id"],
                "title": row["title"],
                "title_source": self._title_source_of(row, meta),
                "profile": row["profile"],
                "workspace": row["workspace"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "status": row["status"],
                "metadata": meta,
                "unread": _message_read_state(meta)["unread"],
                    "archived": bool(meta.get("archived")),
                "agent_id": _session_agent(row["session_id"], meta),
                "messages": [
                    {
                        "id": m["id"],
                        "role": m["role"],
                        "content": m["content"],
                        "timestamp": m["timestamp"],
                        "tool_calls": json.loads(m["tool_calls_json"] or "[]"),
                        **({"parts": json.loads(m["parts_json"])} if m["parts_json"] else {}),
                        **_typed_fields(m),
                    }
                    for m in messages
                ],
            }

            if conversation:
                request_row = conn.execute(
                    "SELECT * FROM client_requests WHERE session_id=? "
                    "AND status NOT IN ('queued', 'paused') ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
                latest = self._request_row(request_row) if request_row else None
                payload["latest_request"] = ({key: latest.get(key) for key in (
                    "session_id", "request_id", "turn_id", "status", "updated_at", "finished_at",
                )} if latest else None)
                if latest and isinstance(latest.get("result", {}).get("error"), str):
                    payload["latest_request"]["error"] = latest["result"]["error"][:4096]
                payload["event_cursor"] = conn.execute(
                    "SELECT COALESCE(MAX(event_id), 0) FROM events WHERE session_id IN (?, '*')",
                    (session_id,),
                ).fetchone()[0]
                partial = []
                # A terminal assistant message already contains the final text.
                has_answer = latest and any(
                    m["role"] == "assistant" and m["timestamp"] >= latest["created_at"]
                    for m in messages
                )
                if latest and not has_answer:
                    for event in conn.execute(
                        "SELECT data_json FROM activity_history WHERE session_id=? AND event='turn.delta' ORDER BY event_id",
                        (session_id,),
                    ):
                        data = json.loads(event["data_json"] or "{}")
                        if data.get("request_id") == latest["request_id"] and isinstance(data.get("delta"), str):
                            partial.append(data["delta"])
                payload["partial_text"] = "".join(partial)
                context = []
                if latest:
                    for event in conn.execute(
                        "SELECT event, data_json FROM activity_history WHERE session_id=? "
                        "AND (event LIKE 'tool.%' OR event='agent.handoff' OR event LIKE 'agent.handoff.%') ORDER BY event_id",
                        (session_id,),
                    ):
                        data = json.loads(event["data_json"] or "{}")
                        if data.get("request_id") == latest["request_id"]:
                            # Handoff events carry their record under `handoff`.
                            # Project identity/status only; never expose tool arguments or worker output here.
                            detail = data.get("handoff") if isinstance(data.get("handoff"), dict) else data
                            context.append({"event": event["event"], **{
                                key: detail[key] for key in ("tool", "text", "phase", "status", "child_run_id", "task_id", "parent_run_id", "from_agent_id", "to_agent_id")
                                if isinstance(detail.get(key), str)
                            }})
                payload["activity_context"] = context[-50:]
            return payload

    def ensure_session(
        self,
        session_id: str,
        *,
        title: str = "New Conversation",
        profile: str = "jaeger",
        workspace: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        meta_str = json.dumps(metadata or {})
        with self._get_conn() as conn:
            if metadata:
                existing = conn.execute(
                    "SELECT metadata_json FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if existing:
                    prior = _row_meta(existing["metadata_json"])
                    prior.update(metadata)
                    meta_str = json.dumps(prior)
            conn.execute(
                """
                INSERT INTO sessions (session_id, title, profile, workspace, created_at, updated_at, status, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, 'idle', ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    metadata_json = CASE
                        WHEN excluded.metadata_json != '{}' THEN excluded.metadata_json
                        ELSE sessions.metadata_json
                    END
                """,
                (session_id, title, profile, workspace, now, now, meta_str),
            )
        return self.get_session(session_id) or {}

    def branch_session(self, session_id: str, *, title: str | None = None,
                       keep_count: int | None = None) -> dict[str, Any] | None:
        """Create an independent Gateway-owned copy of a conversation."""
        source = self.get_session(session_id)
        if source is None:
            return None
        messages = list(source.get("messages") or [])
        if keep_count is not None:
            messages = messages[:max(0, int(keep_count))]
        branch_id = uuid.uuid4().hex
        metadata = dict(source.get("metadata") or {})
        metadata.pop("message_read_state", None)
        metadata.update({"source": "fork", "parent_session_id": session_id})
        branch = self.ensure_session(
            branch_id,
            title=(title or f"{source.get('title') or 'Conversation'} (fork)")[:200],
            profile=source.get("profile") or "jaeger",
            workspace=source.get("workspace") or "",
            metadata=metadata,
        )
        for message in messages:
            self.append_message(
                branch_id, str(message.get("role") or "user"),
                str(message.get("content") or ""),
                tool_calls=message.get("tool_calls") or [],
                timestamp=message.get("timestamp"),
                emit=False,
            )
        return self.get_session(branch_id) or branch

    def rename_session(self, session_id: str, title: str, *, source: str = "user") -> dict[str, Any] | None:
        """Set a session's title. The Gateway owns titles; clients project them.

        Returns the updated session, or ``None`` when the session is unknown.
        Does not touch ``updated_at``: a rename is not conversation activity and
        must not reorder the sidebar. ``source='user'`` (the default) marks the
        title as manual so auto-titling will not overwrite it.
        """
        source = "user" if source != "auto" else "auto"
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET title = ?, title_source = ? WHERE session_id = ?",
                (title, source, session_id),
            )
            if cursor.rowcount == 0:
                return None
            row=conn.execute("SELECT metadata_json FROM sessions WHERE session_id=?",(session_id,)).fetchone()
            meta=json.loads(row[0] or '{}')
            org=meta.setdefault('chat_organization', {})
            org['manual_title']=source=="user"
            org['title_source']=source
            conn.execute("UPDATE sessions SET metadata_json=? WHERE session_id=?",(json.dumps(meta),session_id))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='chat_organization'").fetchone():
                conn.execute("UPDATE chat_organization SET revision=revision+1 WHERE id=1")
        return self.get_session(session_id)

    def apply_auto_title(
        self,
        session_id: str,
        title: str,
        *,
        user_turns: int,
        fingerprint: str,
        model: str,
        changed: bool = True,
        allow_heal: bool = False,
    ) -> bool:
        """Write a model-generated title when the user has not renamed this chat.

        Leaves ``updated_at`` alone so the sidebar does not reorder. Returns
        False when the session is missing or the title is user-owned.
        """
        title = (title or "").strip()[:200]
        if not title:
            return False
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT title, title_source, metadata_json FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                return False
            meta = _row_meta(row["metadata_json"])
            source = self._title_source_of(row, meta)
            if source == "user" and not allow_heal:
                return False
            org = meta.setdefault("chat_organization", {})
            if source == "user":
                org["manual_title"] = False
            org["title_source"] = "auto"
            org["manual_title"] = False
            meta["title_auto"] = {
                "generated": True,
                "updated_at": time.time(),
                "user_turns": int(user_turns),
                "fingerprint": str(fingerprint or ""),
                "model": str(model or ""),
            }
            if changed:
                conn.execute(
                    "UPDATE sessions SET title=?, title_source='auto', metadata_json=? WHERE session_id=?",
                    (title, json.dumps(meta), session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET title_source='auto', metadata_json=? WHERE session_id=?",
                    (json.dumps(meta), session_id),
                )
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='chat_organization'").fetchone():
                conn.execute("UPDATE chat_organization SET revision=revision+1 WHERE id=1")
        return bool(changed)

    def set_session_archived(self, session_id: str, archived: bool) -> dict[str, Any] | None:
        """Set the Gateway-owned archive flag in session metadata.

        Archive state is session organization, not conversation activity, so it
        does not touch ``updated_at`` or reorder the sidebar.
        """
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            metadata = _row_meta(row["metadata_json"])
            metadata["archived"] = bool(archived)
            conn.execute(
                "UPDATE sessions SET metadata_json = ? WHERE session_id = ?",
                (json.dumps(metadata), session_id),
            )
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='chat_organization'").fetchone():
                conn.execute("UPDATE chat_organization SET revision=revision+1 WHERE id=1")
        return self.get_session(session_id)

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        timestamp: float | None = None,
        conn: sqlite3.Connection | None = None,
        parts: list[dict[str, Any]] | None = None,
        kind: str = "message",
        sender_agent_id: str | None = None,
        links: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        emit: bool = True,
    ) -> int:
        """Append one transcript row and, unless ``emit`` is false, publish
        ``message.created {session_id, message}`` on the session and global
        streams once the row's transaction commits."""
        if kind not in _ss('MESSAGE_KINDS'):
            raise ValueError(f"unknown message kind: {kind!r}")
        now = timestamp or time.time()
        tool_str = json.dumps(tool_calls or [])
        parts_str = json.dumps(parts) if parts else None
        links_str = json.dumps({k: v for k, v in links.items() if v is not None}) if links else None
        meta_str = json.dumps(meta) if meta else None

        def _write(db: sqlite3.Connection) -> int:
            cursor = db.execute(
                """
                INSERT INTO messages (session_id, role, content, timestamp, tool_calls_json, parts_json,
                                      kind, sender_agent_id, links_json, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, now, tool_str, parts_str, kind, sender_agent_id, links_str, meta_str),
            )
            db.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            if role == "user" and kind == "message" and (content or "").strip():
                session_row = db.execute(
                    "SELECT title, metadata_json FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if session_row is not None and is_generic_session_title(
                    session_row["title"], _row_meta(session_row["metadata_json"])
                ):
                    auto_title = title_from_user_text(content)
                    if auto_title:
                        db.execute(
                            "UPDATE sessions SET title = ? WHERE session_id = ?",
                            (auto_title, session_id),
                        )
            msg_id = cursor.lastrowid or 0
            if emit:
                row = db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
                payload = {"session_id": session_id, "message": message_dict(row, session_id)}
                self._queue_event(self._insert_event(db, session_id, "message.created", payload, now))
                self._queue_event(self._insert_event(db, "*", "message.created", payload, now))
            return msg_id

        if conn is not None:
            return _write(conn)
        with self._get_conn() as owned:
            msg_id = _write(owned)
        self._flush_events()
        return msg_id

    def list_messages(self, session_id: str, *, before: int | None = None,
                      limit: int = 50, after: int | None = None,
                      until: int | None = None) -> dict[str, Any]:
        """Newest first. ``next_before`` pages to older rows; null at the start."""
        limit = max(1, min(int(limit or 50), _ss('MESSAGES_PAGE_MAX')))
        clauses = ["session_id=?"]
        params: list[Any] = [session_id]
        if before is not None:
            clauses.append("id<?")
            params.append(int(before))
        if after is not None:
            clauses.append("id>=?")
            params.append(int(after))
        if until is not None:
            clauses.append("id<=?")
            params.append(int(until))
        clauses.append(_ss('_HIDDEN_SQL'))
        sql = "SELECT * FROM messages WHERE " + " AND ".join(clauses) + " ORDER BY id DESC LIMIT ?"
        params.append(limit + 1)
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        return {"messages": [message_dict(r, session_id) for r in rows],
                "next_before": rows[-1]["id"] if more and rows else None}

    def messages_after(self, session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        """Oldest first, every row with id > ``after_id`` (summarizer input)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id=? AND id>? AND " + _ss('_HIDDEN_SQL') + " ORDER BY id ASC",
                (session_id, int(after_id or 0)),
            ).fetchall()
        return [message_dict(r, session_id) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        with self._get_conn() as conn:
            res = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM activity_history WHERE session_id = ?", (session_id,))
            return res.rowcount > 0

    def clear_messages(self, session_id: str) -> bool:
        """Drop transcript messages; keep the session row (handoff keep_history=false)."""
        with self._get_conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not exists:
                return False
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (time.time(), session_id),
            )
        return True

    def switch_message_version(self, session_id: str, message_id: int, index: int) -> dict[str, Any] | None:
        """Show a previous edit of a user message and restore its following turns."""
        now = time.time()
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE id=? AND session_id=? AND role='user'",
                (int(message_id), session_id),
            ).fetchone()
            if row is None:
                return None
            meta = _row_meta(row["meta_json"])
            versions = list(meta.get("versions") or [])
            if not (0 <= int(index) < len(versions)):
                raise ValueError("Version is not available")
            all_ids: set[int] = set()
            for version in versions:
                for mid in version.get("following_ids") or []:
                    try:
                        all_ids.add(int(mid))
                    except (TypeError, ValueError):
                        continue
            selected = set()
            for mid in versions[int(index)].get("following_ids") or []:
                try:
                    selected.add(int(mid))
                except (TypeError, ValueError):
                    continue
            for mid in all_ids:
                stored = conn.execute(
                    "SELECT meta_json FROM messages WHERE id=? AND session_id=?",
                    (mid, session_id),
                ).fetchone()
                if stored is None:
                    continue
                extra = _row_meta(stored["meta_json"])
                if mid in selected:
                    extra.pop("hidden", None)
                    extra.pop("hidden_by_edit", None)
                else:
                    extra["hidden"] = True
                    extra["hidden_by_edit"] = int(message_id)
                conn.execute("UPDATE messages SET meta_json=? WHERE id=?", (json.dumps(extra), mid))
            meta["version_index"] = int(index)
            conn.execute(
                "UPDATE messages SET content=?, meta_json=? WHERE id=?",
                (str(versions[int(index)].get("text") or ""), json.dumps(meta), int(message_id)),
            )
            conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id))
            event = self._insert_event(
                conn, session_id, "session.updated",
                {"message_id": int(message_id), "version_index": int(index), "reason": "edit_version"},
                now,
            )
        self._emit([event])
        return self.get_session(session_id, conversation=True)

    def session_local_only(self, session_id: str) -> bool:
        """Keep explicit local-only history local, including auxiliary requests."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT metadata_json FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if row and bool(_row_meta(row[0]).get("local_only")):
                return True
            return conn.execute("SELECT 1 FROM client_requests WHERE session_id=? "
                "AND json_extract(execution_json, '$.options.local_only')=1 LIMIT 1", (session_id,)).fetchone() is not None

    def message_feedback(self, session_id: str) -> dict[str, str]:
        """Return the latest durable rating for each message in a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT data_json FROM activity_history WHERE session_id=? AND event='message.feedback' ORDER BY event_id",
                (session_id,),
            ).fetchall()
        result: dict[str, str] = {}
        for row in rows:
            data = _row_meta(row["data_json"])
            message_id, rating = data.get("message_id"), data.get("rating")
            if message_id is not None and rating in {"positive", "negative"}:
                result[str(message_id)] = rating
        return result

    def message_read_state(self, session_id: str) -> dict[str, Any]:
        """One explicit unread boundary per conversation, shared by all clients."""
        with self._get_conn() as conn:
            row = conn.execute('SELECT metadata_json FROM sessions WHERE session_id=?', (session_id,)).fetchone()
            if row is None:
                raise KeyError('Session not found')
            return _message_read_state(_row_meta(row['metadata_json']))

    def set_message_read_state(self, session_id: str, unread: dict[str, str] | None) -> dict[str, Any]:
        if unread is not None and (
            not isinstance(unread, dict) or set(unread) != {'request_id', 'role'}
            or not isinstance(unread['request_id'], str) or not unread['request_id'].strip()
            or not isinstance(unread['role'], str) or unread['role'] not in {'user', 'assistant'}
        ):
            raise ValueError('Valid request_id and user or assistant role required')
        with self._immediate() as conn:
            row = conn.execute('SELECT metadata_json FROM sessions WHERE session_id=?', (session_id,)).fetchone()
            if row is None:
                raise KeyError('Session not found')
            if unread is not None and conn.execute(
                'SELECT 1 FROM client_requests WHERE session_id=? AND request_id=?',
                (session_id, unread['request_id']),
            ).fetchone() is None:
                raise KeyError('Request not found in this conversation')
            meta = _row_meta(row['metadata_json'])
            previous = _message_read_state(meta)
            if previous['unread'] == unread:
                return {**previous, '_event': None}
            event = self._insert_event(conn, session_id, 'session.read_state', {'unread': unread})
            snapshot = {'unread': unread, 'event_id': event['event_id']}
            meta['message_read_state'] = snapshot
            # A read marker must not change transcript activity ordering.
            conn.execute('UPDATE sessions SET metadata_json=? WHERE session_id=?', (json.dumps(meta), session_id))
            return {**snapshot, '_event': event}

    def message_reactions(self, session_id: str) -> dict[str, Any]:
        """Durable per-request/per-role decoration, independent of SSE retention."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT event_id,data_json FROM activity_history WHERE session_id=? AND event='message.reaction' ORDER BY event_id", (session_id,)).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            data = _row_meta(row['data_json'])
            key = data['request_id'] + '|' + data['role']
            values = result.setdefault(key, [])
            if data['active'] and data['emoji'] not in values:
                values.append(data['emoji'])
            elif not data['active'] and data['emoji'] in values:
                values.remove(data['emoji'])
        return {'reactions': result, 'event_id': rows[-1]['event_id'] if rows else 0}

    def set_message_reaction(self, session_id: str, request_id: str, role: str, emoji: str, active: bool) -> dict:
        from jaeger_ai.contract.message_feedback import REACTION_EMOJIS
        if not isinstance(role, str) or role not in {'user', 'assistant'} or emoji not in REACTION_EMOJIS or type(active) is not bool:
            raise ValueError('Invalid reaction')
        event = None
        with self._immediate() as conn:
            if conn.execute('SELECT 1 FROM client_requests WHERE session_id=? AND request_id=?', (session_id, request_id)).fetchone() is None:
                raise KeyError('Request not found in this conversation')
            row = conn.execute("SELECT data_json FROM activity_history WHERE session_id=? AND event='message.reaction' AND json_extract(data_json,'$.request_id')=? AND json_extract(data_json,'$.role')=? AND json_extract(data_json,'$.emoji')=? ORDER BY event_id DESC LIMIT 1", (session_id, request_id, role, emoji)).fetchone()
            previous = bool(_row_meta(row['data_json']).get('active')) if row else False
            if previous != active:
                event = self._insert_event(conn, session_id, 'message.reaction', {'request_id': request_id, 'role': role, 'emoji': emoji, 'active': active})
        return {**self.message_reactions(session_id), '_event': event}

    def search_session_media(self, session_id: str, query: str, *, after: str = '', limit: int = 25) -> tuple[list[dict[str, Any]], str | None]:
        """Existing session raster attachments only; names never imply file access."""
        from jaeger_ai.contract.file_previews import RASTER_MEDIA_TYPES
        with self._get_conn() as conn:
            conn.create_function('media_casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
            rows = conn.execute(
                "SELECT * FROM attachments WHERE session_id=? AND mime_type IN (?,?,?,?) "
                "AND instr(media_casefold(original_filename),?)>0 AND attachment_id>? ORDER BY attachment_id LIMIT ?",
                (session_id, *RASTER_MEDIA_TYPES, query.casefold(), after, limit + 1),
            ).fetchall()
            result = [{**dict(row), 'metadata': _row_meta(row['metadata_json'])} for row in rows[:limit]]
            return result, result[-1]['attachment_id'] if len(rows) > limit else None

    def append_channel_message_once(self, session_id: str, *, channel: str, conversation_id: str, external_id: str, text: str, author_id: str | None = None) -> dict:
        """Provider message identity, durable inbox delivery only; never run a turn."""
        key = json.dumps(['channel_inbox',channel,conversation_id,external_id])
        digest = input_fingerprint(json.dumps({'session_id':session_id,'text':text,**({'author_id':author_id} if author_id is not None else {})},sort_keys=True))
        with self._immediate() as conn:
            old = conn.execute('SELECT digest,receipt_json FROM background_deliveries WHERE delivery_key=?',(key,)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise ValueError('Provider message identity conflicts with existing delivery; original preserved')
                return {**json.loads(old['receipt_json']),'replayed':True}
            if not conn.execute('SELECT 1 FROM sessions WHERE session_id=?',(session_id,)).fetchone():
                raise ValueError('Bound conversation unavailable')
            # Attribution is literal data, never an authenticated owner claim.
            content = '['+channel+' incoming · '+conversation_id[:160]+']\n'+text
            mid = self.append_message(session_id,'user',content,kind='channel_message',
                meta={'channel_id':channel,'provider_conversation_id':conversation_id,'external_message_id':external_id,**({'ingress_author_id':author_id} if author_id is not None else {}),'authority':'incoming_data_only'},conn=conn)
            receipt={'message_id':mid,'session_id':session_id,'execution_admitted':False}
            conn.execute('INSERT INTO background_deliveries(delivery_key,digest,receipt_json) VALUES(?,?,?)',(key,digest,json.dumps(receipt)))
            return {**receipt,'replayed':False}

    def list_topics(self, session_id: str | None = None, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            self._ensure_session_topics(conn)
            sql = "SELECT * FROM session_topics"
            params: list[Any] = []
            clauses = []
            if session_id:
                clauses.append("session_id=?")
                params.append(session_id)
            if not include_archived:
                clauses.append("archived=0")
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at ASC, start_message_id ASC"
            rows = conn.execute(sql, params).fetchall()
            return [self._topic_dict(row, self._topic_message_count(conn, row)) for row in rows]

    def get_topic(self, topic_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            self._ensure_session_topics(conn)
            row = conn.execute("SELECT * FROM session_topics WHERE topic_id=?", (topic_id,)).fetchone()
            return self._topic_dict(row, self._topic_message_count(conn, row)) if row else None

    def topic_for_message(self, session_id: str, message_id: int) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            self._ensure_session_topics(conn)
            row = conn.execute(
                "SELECT * FROM session_topics WHERE session_id=? AND archived=0 "
                "AND start_message_id<=? AND (end_message_id IS NULL OR end_message_id>=?) "
                "ORDER BY start_message_id DESC LIMIT 1",
                (session_id, message_id, message_id),
            ).fetchone()
        return self._topic_dict(row) if row else None

    def current_topic(self, session_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            self._ensure_session_topics(conn)
            row = conn.execute(
                "SELECT * FROM session_topics WHERE session_id=? AND archived=0 AND end_message_id IS NULL "
                "ORDER BY start_message_id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self._topic_dict(row) if row else None

    def create_topic(
        self,
        session_id: str,
        *,
        title: str = "New conversation",
        title_source: str = "auto",
        start_message_id: int,
        end_message_id: int | None = None,
        summary: str = "",
        metadata: dict[str, Any] | None = None,
        close_open: bool = True,
    ) -> dict[str, Any]:
        topic_id = "topic_" + uuid.uuid4().hex
        now = time.time()
        source = "user" if title_source == "user" else "auto"
        title = (title or "New conversation").strip()[:200] or "New conversation"
        with self._get_conn() as conn:
            self._ensure_session_topics(conn)
            if close_open:
                last = conn.execute(
                    "SELECT MAX(id) FROM messages WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
                close_at = int(start_message_id) - 1
                if last is not None:
                    close_at = min(close_at, int(last))
                if close_at > 0:
                    conn.execute(
                        "UPDATE session_topics SET end_message_id=?, updated_at=? "
                        "WHERE session_id=? AND archived=0 AND end_message_id IS NULL AND start_message_id<=?",
                        (close_at, now, session_id, close_at),
                    )
            conn.execute(
                "INSERT INTO session_topics (topic_id, session_id, title, title_source, start_message_id, "
                "end_message_id, summary, archived, created_at, updated_at, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,0,?,?,?)",
                (topic_id, session_id, title, source, int(start_message_id), end_message_id,
                 summary or "", now, now, json.dumps(metadata or {})),
            )
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='chat_organization'").fetchone():
                conn.execute("UPDATE chat_organization SET revision=revision+1 WHERE id=1")
        topic = self.get_topic(topic_id)
        if topic is None:
            raise RuntimeError("topic was not stored")
        return topic

    def update_topic(
        self,
        topic_id: str,
        *,
        title: str | None = None,
        title_source: str | None = None,
        end_message_id: int | None | object = ...,
        summary: str | None = None,
        archived: bool | None = None,
        metadata: dict[str, Any] | None = None,
        merge_metadata: bool = True,
    ) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            self._ensure_session_topics(conn)
            row = conn.execute("SELECT * FROM session_topics WHERE topic_id=?", (topic_id,)).fetchone()
            if row is None:
                return None
            meta = _row_meta(row["metadata_json"])
            if metadata is not None:
                meta = {**meta, **metadata} if merge_metadata else dict(metadata)
            source = title_source if title_source in {"auto", "user"} else row["title_source"]
            next_title = (title.strip()[:200] if isinstance(title, str) and title.strip() else row["title"])
            end = row["end_message_id"] if end_message_id is ... else end_message_id
            nxt_summary = row["summary"] if summary is None else summary
            nxt_archived = row["archived"] if archived is None else int(bool(archived))
            conn.execute(
                "UPDATE session_topics SET title=?, title_source=?, end_message_id=?, summary=?, archived=?, "
                "updated_at=?, metadata_json=? WHERE topic_id=?",
                (next_title, source, end, nxt_summary, nxt_archived, time.time(), json.dumps(meta), topic_id),
            )
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='chat_organization'").fetchone():
                conn.execute("UPDATE chat_organization SET revision=revision+1 WHERE id=1")
        return self.get_topic(topic_id)

    def delete_topic(self, topic_id: str) -> bool:
        with self._get_conn() as conn:
            self._ensure_session_topics(conn)
            result = conn.execute("DELETE FROM session_topics WHERE topic_id=?", (topic_id,))
            if result.rowcount and conn.execute("SELECT 1 FROM sqlite_master WHERE name='chat_organization'").fetchone():
                conn.execute("UPDATE chat_organization SET revision=revision+1 WHERE id=1")
            return result.rowcount > 0

    def next_message_id(self, session_id: str) -> int:
        with self._get_conn() as conn:
            last = conn.execute("SELECT MAX(id) FROM messages WHERE session_id=?", (session_id,)).fetchone()[0]
        return int(last or 0) + 1

    def _topic_message_count(self, conn: sqlite3.Connection, row: sqlite3.Row) -> int:
        return int(conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=? AND id>=? AND (? IS NULL OR id<=?)",
            (row["session_id"], row["start_message_id"], row["end_message_id"], row["end_message_id"]),
        ).fetchone()[0])

    def _topic_dict(self, row: sqlite3.Row, message_count: int | None = None) -> dict[str, Any]:
        meta = _row_meta(row['metadata_json'])
        return {
            'topic_id': row['topic_id'],
            'session_id': row['session_id'],
            'title': row['title'],
            'title_source': row['title_source'],
            'start_message_id': row['start_message_id'],
            'end_message_id': row['end_message_id'],
            'summary': row['summary'] or '',
            'archived': bool(row['archived']),
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'pinned': bool(meta.get('pinned')),
            'project_id': meta.get('project_id'),
            'section_id': meta.get('section_id'),
            'position': meta.get('position'),
            'metadata': meta,
            'kind': 'topic',
            'message_count': 0 if message_count is None else int(message_count),
        }
