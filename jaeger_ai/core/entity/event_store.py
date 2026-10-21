"""Persistent SQLite Event Store for Jaeger Entity (Pinocchio Architecture).

Stores all entity lifecycle events durably in `<state_root>/entity_events.sqlite3`.
Guarantees:
- WAL mode for concurrent read/write
- Idempotency deduplication by `idempotency_key`
- Chronological ordering and complete event replay for state reconstruction
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from jaeger_ai.core.instance.instance import operator_state_root
from .events import EventType, JaegerEvent

logger = logging.getLogger("jaeger.entity.event_store")

EVENT_STORE_DB_NAME = "entity_events.sqlite3"


class SqliteEventStore:
    """Durable append-only event store backed by SQLite."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is not None:
            self.path = Path(db_path)
        else:
            self.path = operator_state_root() / EVENT_STORE_DB_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entity_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    source TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    salience REAL NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    parent_event_id TEXT DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    provenance_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_events_ts ON entity_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_session ON entity_events(session_id, timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_type ON entity_events(event_type, timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_parent ON entity_events(parent_event_id);
            """)
            try:
                conn.execute("ALTER TABLE entity_events ADD COLUMN parent_event_id TEXT DEFAULT ''")
            except Exception:
                pass

    def append(self, event: JaegerEvent) -> JaegerEvent:
        """Append an event to the store.

        If `idempotency_key` is provided and already exists, the existing event is returned
        without inserting a duplicate.
        """
        with self._transaction() as conn:
            return self._append(conn, event)

    def _append(self, conn, event: JaegerEvent) -> JaegerEvent:
        payload_str = json.dumps(event.payload, ensure_ascii=False)
        prov_str = json.dumps(event.provenance, ensure_ascii=False)

        if event.idempotency_key:
            cur = conn.execute(
                "SELECT * FROM entity_events WHERE idempotency_key = ?",
                (event.idempotency_key,),
            )
            row = cur.fetchone()
            if row:
                return self._row_to_event(row)

        try:
            conn.execute(
                """
                INSERT INTO entity_events (
                    event_id, event_type, actor, source, session_id,
                    timestamp, salience, idempotency_key, parent_event_id,
                    payload_json, provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.actor,
                    event.source,
                    event.session_id,
                    event.timestamp,
                    event.salience,
                    event.idempotency_key,
                    event.parent_event_id,
                    payload_str,
                    prov_str,
                ),
            )
        except sqlite3.IntegrityError:
            cur = conn.execute(
                "SELECT * FROM entity_events WHERE event_id = ?",
                (event.event_id,),
            )
            row = cur.fetchone()
            if row:
                return self._row_to_event(row)
            raise

        return event

    def _episode_state(self, conn, event_id):
        from hashlib import sha256
        row = conn.execute("SELECT * FROM entity_events WHERE event_id=? AND event_type IN ('human.message','agent.response')", (event_id,)).fetchone()
        if row is None:
            raise ValueError('Retained conversational episode not found')
        event = self._row_to_event(row)
        change = conn.execute("SELECT event_id,payload_json FROM entity_events WHERE event_type=? AND parent_event_id=? ORDER BY id DESC LIMIT 1", (EventType.MEMORY_EPISODE_CHANGED.value,event_id,)).fetchone()
        policy = json.loads(change['payload_json']) if change else {}
        return event, {'active':policy.get('active',True), 'annotation':policy.get('annotation',''),
            'revision':sha256((event_id+'\0'+(change['event_id'] if change else 'original')).encode()).hexdigest()}

    def episode_context(self, event_id):
        """Append-only record plus its latest explicit operator recall policy."""
        with self._get_conn() as conn:
            event, state = self._episode_state(conn,event_id)
        return {**state, 'event_id':event.event_id, 'event_type':event.event_type,
            'session_id':event.session_id, 'actor':event.actor, 'source':event.source,
            'timestamp':event.timestamp,
            'text':str(event.payload.get('text') or event.payload.get('agent_response') or '')[:8000]}

    def episode_context_page(self, query='', *, before=None, limit=30):
        if not isinstance(query,str) or len(query)>200 or before is not None and (type(before) is not int or before<=0):
            raise ValueError('Invalid episode query/cursor')
        needle=query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        with self._get_conn() as conn:
            rows=conn.execute("SELECT id,event_id FROM entity_events WHERE event_type IN ('human.message','agent.response') AND id<? AND COALESCE(json_extract(payload_json,'$.text'),json_extract(payload_json,'$.agent_response'),'') LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT ?", (before or 9223372036854775807,'%'+needle+'%',limit+1)).fetchall()
            values=[]
            for row in rows[:limit]:
                event,state=self._episode_state(conn,row['event_id'])
                text=str(event.payload.get('text') or event.payload.get('agent_response') or '')
                values.append({**state,'event_id':event.event_id,'event_type':event.event_type,
                    'session_id':event.session_id,'actor':event.actor,'source':event.source,
                    'timestamp':event.timestamp,'text':text[:8000],'truncated':len(text)>8000})
        return {'episodes':values,'next_before':rows[limit-1]['id'] if len(rows)>limit else None}

    @staticmethod
    def _episode_operation_id(value):
        import re
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',value):
            raise ValueError('Valid immutable episode operation ID required')
        return 'memory:episode:'+value

    def episode_operation(self, operation_id):
        key=self._episode_operation_id(operation_id)
        with self._get_conn() as conn:
            row=conn.execute('SELECT payload_json FROM entity_events WHERE idempotency_key=?',(key,)).fetchone()
        return json.loads(row['payload_json']).get('receipt') if row else None

    def manage_episode(self, event_id, action, *, expected_revision, operation_id, actor, text=None):
        """Atomic CAS plus event/receipt; immutable history is never rewritten.

        Exclusion affects cross-conversation automatic recall only. A correction
        is explicit TOLD advice beside the original, never replacement evidence.
        """
        from dataclasses import replace
        key=self._episode_operation_id(operation_id)
        if action not in {'annotate','forget','restore'} or not isinstance(expected_revision,str) or len(expected_revision)!=64:
            raise ValueError('Invalid episode action/revision')
        if action=='annotate' and (not isinstance(text,str) or not text.strip() or len(text)>8000):
            raise ValueError('Correction note must contain 1–8000 characters')
        command={'event_id':event_id,'action':action,'expected_revision':expected_revision,'actor':actor,'text':text}
        with self._transaction() as conn:
            old=conn.execute('SELECT payload_json FROM entity_events WHERE idempotency_key=?',(key,)).fetchone()
            if old:
                value=json.loads(old['payload_json'])
                if value.get('command')!=command:raise ValueError('Operation ID belongs to a different command')
                return value['receipt']
            original,state=self._episode_state(conn,event_id)
            if state['revision']!=expected_revision:raise ValueError('Episode context changed; inspect current revision')
            if action=='forget' and not state['active'] or action=='restore' and state['active']:
                raise ValueError('Episode recall state already changed')
            active=action!='forget' if action!='annotate' else state['active']
            annotation=text if action=='annotate' else state['annotation']
            receipt={'ok':True,'operation_id':operation_id,'domain':'episode_context','http_status':200,
                'result':{'event_id':event_id,'active':active,'action':action,'original_preserved':True,'scope':'cross_conversation_automatic_context'}}
            event=JaegerEvent.typed(EventType.MEMORY_EPISODE_CHANGED.value,{'command':command,'active':active,'annotation':annotation,'receipt':receipt}, actor=actor,source='memory.controls',session_id=original.session_id,parent_event_id=original.event_id)
            self._append(conn,replace(event,idempotency_key=key))
        return receipt

    def project_recall(self, events):
        """Apply the existing owner's current policy without editing its events."""
        from dataclasses import replace
        result=[]
        with self._get_conn() as conn:
            for event in events:
                _,state=self._episode_state(conn,event.event_id)
                if state['active']:
                    result.append(replace(event,payload={**event.payload,'operator_correction':state['annotation']}))
        return result

    def get_event(self, event_id: str) -> JaegerEvent | None:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM entity_events WHERE event_id = ?",
                (event_id,),
            )
            row = cur.fetchone()
            return self._row_to_event(row) if row else None

    def query_events(
        self,
        *,
        session_id: str | None = None,
        event_type: str | None = None,
        event_types: list[str] | None = None,
        actor: str | None = None,
        since_ts: float | None = None,
        since_id: int | None = None,
        limit: int = 100,
    ) -> list[JaegerEvent]:
        query = "SELECT * FROM entity_events WHERE 1=1"
        params: list[Any] = []

        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        elif event_types:
            placeholders = ",".join("?" for _ in event_types)
            query += f" AND event_type IN ({placeholders})"
            params.extend(event_types)
        if actor:
            query += " AND actor = ?"
            params.append(actor)
        if since_ts is not None:
            query += " AND timestamp >= ?"
            params.append(since_ts)
        if since_id is not None:
            query += " AND id > ?"
            params.append(int(since_id))

        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_event(r) for r in rows]

    def replay_all(self, session_id: str | None = None) -> Iterator[JaegerEvent]:
        """Iterate over all events in strict chronological order for replay/reconstruction."""
        with self._get_conn() as conn:
            if session_id:
                cur = conn.execute(
                    "SELECT * FROM entity_events WHERE session_id = ? ORDER BY id ASC",
                    (session_id,),
                )
            else:
                cur = conn.execute("SELECT * FROM entity_events ORDER BY id ASC")
            for row in cur:
                yield self._row_to_event(row)

    def count_events(self) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT COUNT(*) AS total FROM entity_events")
            return int(cur.fetchone()["total"])

    def count(self) -> int:
        return self.count_events()

    def latest_id(self) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT MAX(id) AS mx FROM entity_events")
            row = cur.fetchone()
            return int(row["mx"] or 0)

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> JaegerEvent:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        try:
            provenance = json.loads(row["provenance_json"] or "{}")
        except json.JSONDecodeError:
            provenance = {}

        parent_id = ""
        try:
            parent_id = str(row["parent_event_id"] or "")
        except (IndexError, KeyError):
            pass
        if not parent_id:
            parent_id = str(provenance.get("parent_event_id") or "")

        return JaegerEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            actor=row["actor"],
            source=row["source"],
            timestamp=float(row["timestamp"]),
            session_id=row["session_id"],
            payload=payload,
            provenance=provenance,
            salience=float(row["salience"]),
            idempotency_key=row["idempotency_key"],
            parent_event_id=parent_id,
        )
