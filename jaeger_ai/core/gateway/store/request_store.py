"""Request admission, approvals, queue, steer & reconcile SQLite store mixin (Wave 4A)."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Callable

def _ss(name: str) -> Any:
    from .. import session_store as _mod
    return getattr(_mod, name)


def _row_meta(*args: Any, **kwargs: Any) -> Any:
    return _ss("_row_meta")(*args, **kwargs)


def _attachment_parts(*args: Any, **kwargs: Any) -> Any:
    return _ss("_attachment_parts")(*args, **kwargs)


def _message_hidden(*args: Any, **kwargs: Any) -> Any:
    return _ss("_message_hidden")(*args, **kwargs)


def _normalize_requested(*args: Any, **kwargs: Any) -> Any:
    return _ss("_normalize_requested")(*args, **kwargs)


def input_fingerprint(*args: Any, **kwargs: Any) -> Any:
    return _ss("input_fingerprint")(*args, **kwargs)


def request_fingerprint(*args: Any, **kwargs: Any) -> Any:
    return _ss("request_fingerprint")(*args, **kwargs)


class RequestStoreMixin:
    """Request admission, approval inbox, turn queue and reconciliation methods."""

    def _queue_event(self, record: dict[str, Any]) -> None:
        pending = getattr(self._pending_events, "items", None)
        if pending is None:
            pending = self._pending_events.items = []
        pending.append(record)

    def release_process(self, pid: int | None = None) -> bool:
        pid = int(pid or os.getpid())
        with self._immediate() as conn:
            changed = conn.execute(
                "DELETE FROM process_lease WHERE id=1 AND owner_pid=?", (pid,)
            )
            return changed.rowcount > 0

    def cancel_model_choice(self, session_id, *, operation_id, expected_revision, actor, requested_model):
        """Resolve an uncertain config intent without undoing any committed choice.

        A receipt already committed wins. Otherwise the original command receives
        a rejection atomically, so an in-flight/late handler cannot apply it.
        This affects no turn/request, tool, permission or model execution.
        """
        fingerprint=self._model_choice_fingerprint(session_id,operation_id,expected_revision,actor,requested_model)
        with self._immediate() as conn:
            prior=conn.execute('SELECT fingerprint,receipt_json FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
            if prior:
                if prior['fingerprint']!=fingerprint:raise ValueError('Model operation ID belongs to another command')
                if prior['receipt_json'] is None:raise ValueError('Incompatible earlier operation unresolved; preserve original')
                return json.loads(prior['receipt_json'])
            if conn.execute('SELECT 1 FROM sessions WHERE session_id=?',(session_id,)).fetchone() is None:raise ValueError('Session not found')
            receipt={'ok':False,'operation_id':operation_id,'domain':'model_choice','session_id':session_id,'http_status':409,
                'error':'Pending model choice cancelled before commit; current model unchanged', 'result':{'cancelled':True}}
            conn.execute("INSERT INTO control_operations VALUES(?,?,'settled',?,?)",(operation_id,fingerprint,json.dumps(receipt),time.time()))
        return receipt

    def _request_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "request_id": row["request_id"],
            "session_id": row["session_id"],
            "digest": row["digest"],
            "turn_id": row["turn_id"],
            "native_run_id": row["native_run_id"],
            "native_session": row["native_session"],
            "status": row["status"],
            "input_text": row["input_text"],
            "result": json.loads(row["result_json"] or "{}"),
            "owner_pid": row["owner_pid"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "execution": _row_meta(row["execution_json"]) if "execution_json" in row.keys() else {},
            "digest_version": row["digest_version"] if "digest_version" in row.keys() else 1,
            "queue_position": row["queue_position"] if "queue_position" in row.keys() else 0,
        }

    def list_requests(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM client_requests WHERE status=? ORDER BY created_at",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM client_requests ORDER BY created_at"
                ).fetchall()
            return [self._request_row(r) for r in rows]

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._request_row(row) if row else None

    def get_request_by_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE turn_id=?", (turn_id,)
            ).fetchone()
            return self._request_row(row) if row else None

    def latest_request(self, session_id: str) -> dict[str, Any] | None:
        """Return the most recent admitted request for a session."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE session_id=? "
                "AND status NOT IN ('queued', 'paused') "
                "ORDER BY created_at DESC LIMIT 1", (session_id,),
            ).fetchone()
            return self._request_row(row) if row else None

    def previous_terminal_request(
        self, session_id: str, *, before_request_id: str,
    ) -> dict[str, Any] | None:
        """Return the terminal request immediately before ``before_request_id``.

        This is a receipt read, not transcript inference.  The explicit current
        request boundary prevents a self-audit turn from selecting itself while
        it is running.
        """
        with self._get_conn() as conn:
            current = conn.execute(
                "SELECT created_at FROM client_requests WHERE request_id=? AND session_id=?",
                (before_request_id, session_id),
            ).fetchone()
            if current is None:
                return None
            row = conn.execute(
                "SELECT * FROM client_requests WHERE session_id=? AND request_id<>? "
                "AND created_at<=? AND status IN ('completed','failed','cancelled','execution_unknown') "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (session_id, before_request_id, current["created_at"]),
            ).fetchone()
            return self._request_row(row) if row else None

    def request_tool_names(self, session_id: str, request_id: str) -> list[str]:
        """Tool names from durable lifecycle events, in first-start order."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT data_json FROM activity_history WHERE session_id=? "
                "AND event='tool.started' AND json_extract(data_json,'$.request_id')=? "
                "ORDER BY event_id",
                (session_id, request_id),
            ).fetchall()
        return [
            str(data["tool"])
            for row in rows
            if isinstance((data := _row_meta(row["data_json"])).get("tool"), str)
            and data["tool"]
        ]

    def sessions_with_queue(self) -> list[str]:
        """Sessions that still own queued or paused follow-up work."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT session_id FROM client_requests "
                "WHERE status IN ('queued', 'paused') ORDER BY session_id"
            ).fetchall()
            return [r["session_id"] for r in rows]

    def list_queue(self, session_id: str) -> list[dict[str, Any]]:
        """Gateway-owned follow-up queue, ordered by explicit position."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM client_requests WHERE session_id=? AND status IN ('queued', 'paused') "
                "ORDER BY queue_position, created_at, request_id",
                (session_id,),
            ).fetchall()
            return [self._request_row(r) for r in rows]

    def enqueue_request(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str | None = None,
        requested: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically add a durable follow-up request without starting it.

        A queued item is a real client_request with a frozen execution snapshot.
        It is not transcript-visible until promotion, because the operator may
        edit or remove it before it runs. The session's one-active-turn
        invariant is unchanged.
        """
        if not str(text or "").strip():
            raise ValueError("Missing queue text")
        text = str(text).strip()
        rid = str(request_id or uuid.uuid4().hex)
        if not rid or len(rid) > _ss('REQUEST_ID_MAX'):
            raise ValueError("Invalid request_id")
        choices = _normalize_requested(requested)
        digest = request_fingerprint(text, choices)
        now = time.time()
        pid = os.getpid()
        with self._immediate() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, title, profile, workspace, created_at, updated_at, status, metadata_json)
                VALUES (?, 'New Conversation', 'jaeger', '', ?, ?, 'idle', '{}')
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id, now, now),
            )
            existing = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (rid,)
            ).fetchone()
            if existing:
                if existing["digest_version"] == 1:
                    same = existing["digest"] == input_fingerprint(text)
                else:
                    same = existing["digest"] == digest
                if not same:
                    raise _ss('RequestConflict')("Request identity was already used for different input")
                payload = self._request_row(existing)
                payload["replayed"] = True
                payload["accepted"] = False
                return payload
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM client_requests WHERE session_id=? AND status IN ('queued', 'paused')",
                (session_id,),
            ).fetchone()["n"]
            if count >= _ss('MAX_QUEUE_PER_SESSION'):
                raise _ss('RequestBusy')("Session queue is full")
            session = conn.execute(
                "SELECT workspace, metadata_json FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            meta = _row_meta(session["metadata_json"] if session else "{}")
            execution = self._resolve_execution(conn, session_id, choices, meta,
                                                session["workspace"] if session else "")
            position = conn.execute(
                "SELECT COALESCE(MAX(queue_position), 0) + 1 AS p FROM client_requests "
                "WHERE session_id=? AND status IN ('queued', 'paused')",
                (session_id,),
            ).fetchone()["p"]
            turn_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO client_requests (
                    request_id, session_id, digest, turn_id, native_run_id, native_session,
                    status, input_text, result_json, owner_pid, created_at, updated_at,
                    execution_json, digest_version, queue_position, requested_json
                ) VALUES (?, ?, ?, ?, NULL, NULL, 'queued', ?, '{}', ?, ?, ?, ?, ?, ?, ?)
                """,
                (rid, session_id, digest, turn_id, text, pid, now, now,
                 json.dumps(execution, sort_keys=True), _ss('REQUEST_FINGERPRINT_VERSION'), int(position),
                 json.dumps(choices, sort_keys=True)),
            )
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (rid,)
            ).fetchone()
            payload = self._request_row(row)
            payload.update({
                "replayed": False,
                "accepted": True,
                "queued": True,
            })
            return payload

    def update_queue_item(
        self,
        session_id: str,
        request_id: str,
        *,
        text: str | None = None,
        status: str | None = None,
        position: int | None = None,
        expected_updated_at: float | None = None,
    ) -> dict[str, Any] | None:
        """Edit only a still-queued item; running work is immutable."""
        if status is not None and status not in _ss('QUEUE_STATUSES'):
            raise ValueError("Queue status must be queued or paused")
        now = time.time()
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=? AND session_id=?",
                (request_id, session_id),
            ).fetchone()
            if row is None or row["status"] not in _ss('QUEUE_STATUSES'):
                return None
            if expected_updated_at is not None and row['updated_at'] != expected_updated_at:
                raise _ss('RequestConflict')('Queued request changed; refresh before editing')
            if text is not None:
                clean = str(text).strip()
                if not clean:
                    raise ValueError("Queue text cannot be empty")
                requested = _row_meta(row["requested_json"]) if "requested_json" in row.keys() else {}
                digest = request_fingerprint(clean, requested)
                conn.execute(
                    "UPDATE client_requests SET input_text=?, digest=?, updated_at=? WHERE request_id=?",
                    (clean, digest, now, request_id),
                )
            if status is not None:
                conn.execute(
                    "UPDATE client_requests SET status=?, updated_at=? WHERE request_id=?",
                    (status, now, request_id),
                )
            if position is not None:
                clean_pos = max(1, int(position))
                conn.execute(
                    "UPDATE client_requests SET queue_position=?, updated_at=? WHERE request_id=?",
                    (clean_pos, now, request_id),
                )
            updated = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._request_row(updated) if updated else None

    def reorder_queue(self, session_id: str, ordered_ids: list[str]) -> list[dict[str, Any]]:
        """Assign explicit positions to every queued/paused item in one transaction."""
        ids = [str(v).strip() for v in ordered_ids if str(v).strip()]
        with self._immediate() as conn:
            rows = conn.execute(
                "SELECT request_id FROM client_requests WHERE session_id=? AND status IN ('queued', 'paused')",
                (session_id,),
            ).fetchall()
            existing = {r["request_id"] for r in rows}
            if len(ids) != len(existing) or set(ids) != existing:
                raise ValueError("Queue order must name every queued item exactly once")
            for position, rid in enumerate(ids, 1):
                conn.execute(
                    "UPDATE client_requests SET queue_position=?, updated_at=? WHERE request_id=? AND session_id=?",
                    (position, time.time(), rid, session_id),
                )
        return self.list_queue(session_id)

    def delete_queue_item(self, session_id: str, request_id: str) -> bool:
        with self._immediate() as conn:
            changed = conn.execute(
                "DELETE FROM client_requests WHERE request_id=? AND session_id=? AND status IN ('queued', 'paused')",
                (request_id, session_id),
            )
            return changed.rowcount > 0

    def promote_next_queue_item(self, session_id: str) -> dict[str, Any] | None:
        """Promote one queued request only when the session is idle.

        This is the queue drain point. Paused items are skipped, and a busy
        or unreconciled session cannot start new work.
        """
        now = time.time()
        with self._immediate() as conn:
            session = conn.execute(
                "SELECT status, workspace, metadata_json FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if session is None or session["status"] in {"running", "execution_unknown", "cancelling"}:
                return None
            row = conn.execute(
                "SELECT * FROM client_requests WHERE session_id=? AND status='queued' "
                "ORDER BY queue_position, created_at, request_id LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            execution = _row_meta(row["execution_json"])
            visible = execution.get("display_text") or row["input_text"]
            msg_id = self.append_message(session_id, "user", visible, timestamp=now, conn=conn,
                                         meta={"request_id": row["request_id"], "turn_id": row["turn_id"]},
                                         parts=_attachment_parts(conn, session_id, execution))
            meta = _row_meta(session["metadata_json"])
            choices = _row_meta(row['requested_json'])
            # A queued implicit default is an execution snapshot, not authority
            # to revert a newer explicit conversation preference on promotion.
            if 'model' in choices:
                meta['model'] = execution.get('model')
                meta['provider'] = execution.get('provider')
            elif 'provider' in choices:
                meta['provider'] = execution.get('provider')
            if 'model' in choices or 'provider' in choices:
                meta['model_choice_revision'] = self.model_choice_revision(meta) + 1
            conn.execute(
                "UPDATE client_requests SET status='admitted', updated_at=? WHERE request_id=?",
                (now, row["request_id"]),
            )
            conn.execute(
                "UPDATE sessions SET status='running', metadata_json=?, updated_at=? WHERE session_id=?",
                (json.dumps(meta), now, session_id),
            )
            event = self._insert_event(
                conn,
                session_id,
                "turn.start",
                {
                    "turn_id": row["turn_id"],
                    "request_id": row["request_id"],
                    "message_id": msg_id,
                    "text": visible,
                },
                now,
            )
            updated = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (row["request_id"],)
            ).fetchone()
            payload = self._request_row(updated)
            payload.update({
                "event": event,
                "message_id": msg_id,
                "accepted": True,
                "replayed": False,
            })
            return payload

    def admit_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Admit a turn (see ``_admit_request``). A session left ``execution_unknown`` by an earlier
        turn is acknowledged first (outcome stays unknown, nothing is replayed) so one unknown
        outcome never locks the conversation; the acknowledgement events go to ``event_sink``."""
        events: list[dict[str, Any]] = []
        payload = self._admit_request(*args, _ack_events=events, **kwargs)
        self._emit(events)
        if events:
            payload["acknowledged_unknown"] = [e["data"]["request_id"] for e in events]
        return payload

    def _admit_request(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str | None = None,
        requested: dict[str, Any] | None = None,
        expected_model_revision: int | None = None,
        admission_guard: Callable[[sqlite3.Connection], None] | None = None,
        retry_of: str | None = None,
        edit_message_id: int | None = None,
        _ack_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Atomically accept a client request and freeze what it executes.

        ``requested`` carries the client's explicit execution choices
        (``EXECUTION_INPUT_KEYS``). They are part of the request identity:
        an identical retry replays the original receipt and changes nothing;
        the same request_id with a different text *or* different choices is
        a :class:`RequestConflict`.

        On acceptance the *resolved* execution input — explicit choices, else
        the session's current defaults, plus the attachment revisions present
        right now — is persisted with the request in the same transaction.
        Execution reads that snapshot, so a later session edit or upload can
        never alter a request that was already admitted. An explicit model
        choice also becomes the session default for later turns (existing
        continuity contract), but only when the request is accepted, never on
        replay.

        Pre-upgrade receipts (``digest_version`` 1, text-only digest) replay
        by their original digest with their original (empty) snapshot; they
        are never recomputed under the new schema or executed again.

        Returns a dict with ``replayed`` True when an existing execution is
        returned. Raises RequestConflict / RequestBusy on illegal reuse and
        ValueError on invalid input (including unknown attachment ids).
        """
        if not str(text or "").strip():
            raise ValueError("Missing turn text")
        text = str(text).strip()
        rid = str(request_id or uuid.uuid4().hex)
        if not rid or len(rid) > _ss('REQUEST_ID_MAX'):
            raise ValueError("Invalid request_id")
        choices = _normalize_requested(requested)
        digest = request_fingerprint(text, choices)
        now = time.time()
        pid = os.getpid()
        with self._immediate() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, title, profile, workspace, created_at, updated_at, status, metadata_json)
                VALUES (?, 'New Conversation', 'jaeger', '', ?, ?, 'idle', '{}')
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id, now, now),
            )
            existing = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (rid,)
            ).fetchone()
            if existing:
                if existing["digest_version"] == 1:
                    same = existing["digest"] == input_fingerprint(text)
                else:
                    same = existing["digest"] == digest
                if not same:
                    raise _ss('RequestConflict')(
                        "Request identity was already used for different input"
                    )
                payload = self._request_row(existing)
                payload["replayed"] = True
                payload["accepted"] = False
                return payload
            session = conn.execute(
                "SELECT status, workspace, metadata_json FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            status = session["status"] if session else "idle"
            if status == "execution_unknown":
                acked = self._acknowledge_unknown(conn, session_id, actor="admission", now=now)
                if _ack_events is not None:
                    _ack_events.extend(acked)
                status = "idle"
            if status in {"running", "execution_unknown", "cancelling"}:
                raise _ss('RequestBusy')(
                    "Previous execution needs reconciliation before another turn"
                    if status == "execution_unknown"
                    else "Turn already in progress"
                )
            meta = _row_meta(session["metadata_json"] if session else "{}")
            if expected_model_revision is not None and self.model_choice_revision(meta)!=expected_model_revision:
                raise _ss('RequestConflict')("Conversation model changed during validation; no new request admitted")
            execution = self._resolve_execution(conn, session_id, choices, meta,
                                                session["workspace"] if session else "")
            if "model" in choices:
                meta["model"] = choices["model"]
                if choices.get("provider"):
                    meta["provider"] = choices["provider"]
                else:
                    # A new model without a provider must not inherit the
                    # previous model's provider (it was paired with that model).
                    meta.pop("provider", None)
            elif choices.get("provider"):
                meta["provider"] = choices["provider"]
            if "model" in choices or "provider" in choices:
                meta["model_choice_revision"] = self.model_choice_revision(meta) + 1
            if admission_guard is not None:
                admission_guard(conn)
            turn_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO client_requests (
                    request_id, session_id, digest, turn_id, native_run_id, native_session,
                    status, input_text, result_json, owner_pid, created_at, updated_at,
                    execution_json, digest_version
                ) VALUES (?, ?, ?, ?, NULL, NULL, 'admitted', ?, '{}', ?, ?, ?, ?, ?)
                """,
                (rid, session_id, digest, turn_id, text, pid, now, now,
                 json.dumps(execution, sort_keys=True), _ss('REQUEST_FINGERPRINT_VERSION')),
            )
            visible = choices["display_text"] if "display_text" in choices else text
            if retry_of:
                previous = conn.execute(
                    "SELECT request_id, status FROM client_requests WHERE request_id=? AND session_id=?",
                    (retry_of, session_id),
                ).fetchone()
                if previous is None or previous["status"] in {"running", "admitted", "cancelling"}:
                    raise _ss('RequestConflict')("Previous request is unavailable for retry")
                original = conn.execute(
                    "SELECT id FROM messages WHERE session_id=? AND role='user' "
                    "AND json_extract(meta_json, '$.request_id')=? ORDER BY id DESC LIMIT 1",
                    (session_id, retry_of),
                ).fetchone()
                if original is None:
                    raise _ss('RequestConflict')("Previous user turn is unavailable for retry")
                msg_id = original["id"]
                # The reused message now belongs to this retry. A later retry
                # finds it through the latest request without duplicating the turn.
                conn.execute(
                    "UPDATE messages SET meta_json=? WHERE id=?",
                    (json.dumps({"request_id": rid, "turn_id": turn_id}), msg_id),
                )
                # Replace the visible answer while retaining its durable receipt/events.
                conn.execute(
                    "DELETE FROM messages WHERE session_id=? AND role='assistant' "
                    "AND json_extract(meta_json, '$.request_id')=?", (session_id, retry_of),
                )
            elif edit_message_id is not None:
                mid = int(edit_message_id)
                original = conn.execute(
                    "SELECT * FROM messages WHERE id=? AND session_id=? AND role='user'",
                    (mid, session_id),
                ).fetchone()
                if original is None:
                    raise ValueError("User message is unavailable to edit")
                self._ensure_session_topics(conn)
                topic = conn.execute(
                    "SELECT start_message_id, end_message_id FROM session_topics "
                    "WHERE session_id=? AND archived=0 AND start_message_id<=? "
                    "AND (end_message_id IS NULL OR end_message_id>=?) "
                    "ORDER BY start_message_id DESC LIMIT 1",
                    (session_id, mid, mid),
                ).fetchone()
                end_id = int(topic["end_message_id"]) if topic and topic["end_message_id"] is not None else None
                following = conn.execute(
                    "SELECT id, meta_json FROM messages WHERE session_id=? AND id>? "
                    "AND (? IS NULL OR id<=?) ORDER BY id",
                    (session_id, mid, end_id, end_id),
                ).fetchall()
                visible_following = [int(row["id"]) for row in following if not _message_hidden(row["meta_json"])]
                meta_msg = _row_meta(original["meta_json"])
                versions = list(meta_msg.get("versions") or [])
                if not versions:
                    versions.append({
                        "text": original["content"] or "",
                        "following_ids": visible_following,
                        "created_at": original["timestamp"],
                    })
                else:
                    idx = meta_msg.get("version_index")
                    idx = idx if isinstance(idx, int) else len(versions) - 1
                    if 0 <= idx < len(versions) and not versions[idx].get("following_ids"):
                        versions[idx] = {**versions[idx], "following_ids": visible_following}
                versions.append({"text": visible, "following_ids": [], "created_at": now})
                new_meta = {
                    **meta_msg,
                    "request_id": rid,
                    "turn_id": turn_id,
                    "versions": versions,
                    "version_index": len(versions) - 1,
                    "hidden": False,
                }
                conn.execute(
                    "UPDATE messages SET content=?, meta_json=?, timestamp=? WHERE id=?",
                    (visible, json.dumps(new_meta), now, mid),
                )
                for fid in visible_following:
                    row = conn.execute("SELECT meta_json FROM messages WHERE id=?", (fid,)).fetchone()
                    extra = _row_meta(row["meta_json"] if row else None)
                    extra["hidden"] = True
                    extra["hidden_by_edit"] = mid
                    conn.execute("UPDATE messages SET meta_json=? WHERE id=?", (json.dumps(extra), fid))
                msg_id = mid
            else:
                msg_id = self.append_message(session_id, "user", visible, timestamp=now, conn=conn,
                                             meta={"request_id": rid, "turn_id": turn_id},
                                             parts=_attachment_parts(conn, session_id, execution))
            conn.execute(
                "UPDATE sessions SET status='running', metadata_json=?, updated_at=? WHERE session_id=?",
                (json.dumps(meta), now, session_id),
            )
            event = self._insert_event(
                conn,
                session_id,
                "turn.start",
                {"turn_id": turn_id, "request_id": rid, "message_id": msg_id, "text": visible},
                now,
            )
            return {
                "request_id": rid,
                "session_id": session_id,
                "digest": digest,
                "turn_id": turn_id,
                "native_run_id": None,
                "native_session": None,
                "status": "admitted",
                "input_text": text,
                "result": {},
                "owner_pid": pid,
                "created_at": now,
                "updated_at": now,
                "execution": execution,
                "digest_version": _ss('REQUEST_FINGERPRINT_VERSION'),
                "message_id": msg_id,
                "event": event,
                "replayed": False,
                "accepted": True,
            }

    def complete_request(
        self,
        request_id: str,
        *,
        status: str,
        result: dict[str, Any],
        assistant_text: str | None = None,
        session_status: str | None = None,
        event_name: str | None = None,
        follow_ups: list[str] | None = None,
    ) -> dict[str, Any]:
        """Commit result, transcript and terminal event together, once."""
        event_name = event_name or {
            "completed": "turn.finish", "failed": "turn.failed",
            "cancelled": "turn.cancelled", "execution_unknown": "turn.unknown",
        }[status]
        now = time.time()
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown request {request_id}")
            if row["status"] in {"completed", "failed", "cancelled"}:
                payload = self._request_row(row)
                payload["replayed"] = True
                return payload
            conn.execute(
                "UPDATE client_requests SET status=?, result_json=?, updated_at=? WHERE request_id=?",
                (status, json.dumps(result), now, request_id),
            )
            sess_status = session_status or ("idle" if status == "completed" else status)
            conn.execute(
                "UPDATE sessions SET status=?, updated_at=? WHERE session_id=?",
                (sess_status, now, row["session_id"]),
            )
            updated = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            payload = self._request_row(updated)
            payload["replayed"] = False
            # Count catalog search invocations from this request's durable tool lifecycle.
            # Started calls count even if interrupted; completed and failed are
            # independently observed outcomes. This runs in the terminal transaction.
            search_tools = {
                "search_files", "grep_files", "grep_search", "search_memory",
                "session_search", "library_search", "web_search", "docs_search",
                "search_docs", "jaeger.search", "docs.search", "web.search",
            }
            search_events = conn.execute(
                "SELECT event, data_json FROM activity_history WHERE session_id=? "
                "AND event IN ('tool.started', 'tool.completed', 'tool.failed') "
                "AND json_extract(data_json, '$.request_id')=? ORDER BY event_id",
                (row["session_id"], request_id),
            )
            starts: set[str] = set()
            completed: set[str] = set()
            failed: set[str] = set()
            for tool_event in search_events:
                data = json.loads(tool_event["data_json"] or "{}")
                if data.get("tool") not in search_tools:
                    continue
                call_id = str(data.get("activity_id") or data.get("call_id") or "")
                if not call_id:
                    continue
                if tool_event["event"] == "tool.started":
                    starts.add(call_id)
                elif tool_event["event"] == "tool.completed":
                    completed.add(call_id)
                else:
                    failed.add(call_id)
            if starts:
                payload["search_count_event"] = self._insert_event(
                    conn, row["session_id"], "search.count",
                    {"session_id": row["session_id"], "request_id": request_id,
                     "turn_id": row["turn_id"], "searches": len(starts),
                     "completed": len(starts & completed), "failed": len(starts & failed)}, now,
                )
            if follow_ups and status == "completed":
                payload["follow_up_event"] = self._insert_event(
                    conn, row["session_id"], "follow_ups",
                    {"request_id": request_id, "turn_id": row["turn_id"], "follow_ups": follow_ups}, now,
                )
            if assistant_text is not None:
                from jaeger_ai.core.gateway.turn_parts import PART_EVENTS, project_parts
                marks = ",".join("?" * len(PART_EVENTS))
                turn_events = [
                    {"event": e["event"], "data": json.loads(e["data_json"] or "{}"), "timestamp": e["timestamp"]}
                    for e in conn.execute(
                        f"SELECT event, data_json, timestamp FROM activity_history WHERE session_id=? AND event IN ({marks}) "
                        "AND json_extract(data_json, '$.request_id')=? ORDER BY event_id ASC",
                        (row["session_id"], *PART_EVENTS, request_id),
                    )
                ]
                turn_parts = project_parts(turn_events, assistant_text)
                if assistant_text and not any(p["type"] == "text" for p in turn_parts):
                    turn_parts.append({"type": "text", "text": assistant_text, "role": "final", "item_id": "final"})
                for appr in conn.execute(
                    "SELECT approval_id, kind, status, decision, metadata_json FROM approvals "
                    "WHERE request_id=? ORDER BY created_at", (request_id,)):
                    ameta = _row_meta(appr["metadata_json"])
                    turn_parts.append({"type": "approval", "approval_id": appr["approval_id"],
                                       "call_id": ameta.get("call_id"), "tool": ameta.get("tool"),
                                       "target": ameta.get("target"), "status": appr["status"],
                                       "decision": appr["decision"]})
                self.append_message(row["session_id"], "assistant", assistant_text, timestamp=now, conn=conn,
                                    meta={"request_id": request_id, "turn_id": row["turn_id"]},
                                    parts=turn_parts or None)
            payload["event"] = self._insert_event(
                conn, row["session_id"], event_name,
                {**result, "request_id": request_id, "turn_id": row["turn_id"], "status": status}, now,
            )
            return payload

    def mark_request_status(self, request_id: str, status: str) -> dict[str, Any] | None:
        now = time.time()
        with self._immediate() as conn:
            changed = conn.execute(
                "UPDATE client_requests SET status=?, updated_at=? WHERE request_id=? "
                "AND status NOT IN ('completed', 'failed', 'cancelled') "
                "AND NOT (status='execution_unknown' AND ?='cancelling')",
                (status, now, request_id, status),
            )
            if changed.rowcount == 0:
                row = conn.execute(
                    "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
                ).fetchone()
                return self._request_row(row) if row else None
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._request_row(row) if row else None

    def steering_record(self, session_id: str, request_id: str, steering_id: str) -> dict[str, Any] | None:
        """Read the original steering receipt from durable activity, even after event retention."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT event_id, data_json FROM activity_history WHERE session_id=? AND event='turn.steer' "
                "AND json_extract(data_json, '$.request_id')=? AND json_extract(data_json, '$.steering_id')=? "
                "ORDER BY event_id LIMIT 1", (session_id, request_id, steering_id),
            ).fetchone()
        return {**json.loads(row['data_json']), 'event_id': row['event_id']} if row else None

    def create_approval(
        self,
        *,
        kind: str,
        prompt: str,
        options: list[str],
        session_id: str | None = None,
        request_id: str | None = None,
        fingerprint: str | None = None,
        metadata: dict[str, Any] | None = None,
        approval_id: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        aid = approval_id or f"approval_{uuid.uuid4().hex[:12]}"
        def insert(conn):
            conn.execute(
                """
                INSERT INTO approvals(
                    approval_id, session_id, request_id, kind, prompt, options_json,
                    status, decision, fingerprint, created_at, resolved_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?, NULL, ?)
                """,
                (
                    aid,
                    session_id,
                    request_id,
                    kind,
                    prompt,
                    json.dumps(list(options)),
                    fingerprint,
                    now,
                    json.dumps(metadata or {}),
                ),
            )
            return self._approval_row(conn.execute("SELECT * FROM approvals WHERE approval_id=?", (aid,)).fetchone())
        if connection is not None:
            if not connection.in_transaction:
                raise ValueError("Approval admission requires an owner transaction")
            return insert(connection)
        with self._immediate() as conn:
            return insert(conn)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            return self._approval_row(row) if row else None

    def _approval_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "approval_id": row["approval_id"],
            "session_id": row["session_id"],
            "request_id": row["request_id"],
            "kind": row["kind"],
            "prompt": row["prompt"],
            "options": json.loads(row["options_json"] or "[]"),
            "status": row["status"],
            "decision": row["decision"],
            "fingerprint": row["fingerprint"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
            "metadata": _row_meta(row["metadata_json"]),
        }

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status='pending' ORDER BY created_at"
            ).fetchall()
            return [self._approval_row(r) for r in rows]

    def create_clarify(self, *, session_id: str, request_id: str | None, question: str,
                       choices: list[str] | tuple[str, ...] = (), clarify_id: str | None = None) -> dict[str, Any]:
        cid = clarify_id or f"clarify_{uuid.uuid4().hex[:12]}"
        with self._immediate() as conn:
            conn.execute(
                "INSERT INTO clarify_forms (clarify_id, session_id, request_id, question, choices_json, revision,"
                " status, created_at) VALUES (?,?,?,?,?,1,'pending',?)",
                (cid, session_id, request_id, question, json.dumps(list(choices)), time.time()),
            )
        return self.get_clarify(cid) or {}

    def _clarify_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {"clarify_id": row["clarify_id"], "session_id": row["session_id"], "request_id": row["request_id"],
                "question": row["question"], "choices": json.loads(row["choices_json"] or "[]"),
                "revision": int(row["revision"]), "status": row["status"], "answer": row["answer"],
                "created_at": row["created_at"], "resolved_at": row["resolved_at"]}

    def get_clarify(self, clarify_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM clarify_forms WHERE clarify_id=?", (clarify_id,)).fetchone()
            return self._clarify_row(row) if row else None

    def list_clarify(self, session_id: str, *, pending_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM clarify_forms WHERE session_id=?" + (" AND status='pending'" if pending_only else "")
        with self._get_conn() as conn:
            return [self._clarify_row(r) for r in conn.execute(sql + " ORDER BY created_at", (session_id,)).fetchall()]

    def resolve_clarify(self, clarify_id: str, *, revision: int, status: str,
                        answer: str | None = None) -> dict[str, Any] | None:
        """First terminal decision wins for the current revision; stale or repeated returns None."""
        if status not in {"answered", "cancelled", "expired"}:
            raise ValueError(f"bad clarify status {status!r}")
        with self._immediate() as conn:
            cur = conn.execute(
                "UPDATE clarify_forms SET status=?, answer=?, resolved_at=? "
                "WHERE clarify_id=? AND status='pending' AND revision=?",
                (status, answer if status == "answered" else None, time.time(), clarify_id, int(revision)),
            )
            if cur.rowcount != 1:
                return None
        return self.get_clarify(clarify_id)

    def expire_orphaned_clarify(self) -> int:
        """Pending forms from a previous process have no waiting turn; close them as expired."""
        with self._immediate() as conn:
            return conn.execute(
                "UPDATE clarify_forms SET status='expired', resolved_at=? WHERE status='pending'", (time.time(),),
            ).rowcount

    def resolve_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        decision: str | None = None,
        expected_session_id: str | None = None,
        expected_request_id: str | None = None,
        expected_profile: str | None = None,
    ) -> dict[str, Any] | None:
        """First writer wins. Duplicate or stale ids return None."""
        now = time.time()
        choice = decision or ("once" if approved else "deny")
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            if row is None or row["status"] != "pending":
                return None
            if any(value is not None for value in (expected_session_id, expected_request_id, expected_profile)):
                # Native recovered decisions bind to the exact still-live permission context.
                if not all((expected_session_id, expected_request_id, expected_profile)):
                    return None
                if row["session_id"] != expected_session_id or row["request_id"] != expected_request_id:
                    return None
                session = conn.execute("SELECT profile FROM sessions WHERE session_id=?", (expected_session_id,)).fetchone()
                request = conn.execute("SELECT session_id, status FROM client_requests WHERE request_id=?", (expected_request_id,)).fetchone()
                if (not session or session["profile"] != expected_profile or not request
                        or request["session_id"] != expected_session_id
                        or request["status"] not in ("admitted", "running", "awaiting_approval")
                        or choice not in json.loads(row["options_json"] or "[]")):
                    return None
            conn.execute(
                "UPDATE approvals SET status='resolved', decision=?, resolved_at=? WHERE approval_id=?",
                (choice, now, approval_id),
            )
            updated = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            return self._approval_row(updated) if updated else None

    def wait_for_approval(self, approval_id: str, *, timeout_s: float = 120.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            row = self.get_approval(approval_id)
            if row is None:
                return {"approval_id": approval_id, "status": "missing", "decision": "deny"}
            if row["status"] == "resolved":
                return row
            time.sleep(0.05)
        self.resolve_approval(approval_id, approved=False, decision="deny")
        return self.get_approval(approval_id) or {
            "approval_id": approval_id,
            "status": "resolved",
            "decision": "deny",
        }
