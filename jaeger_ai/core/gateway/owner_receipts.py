"""Request-qualified resident outcomes, fenced by the Gateway's existing lease.

An inner run checkpoint is not a request receipt. Only the Gateway producer,
when its entire synchronous continuation has returned, can commit this proof.
The journal is not a queue and never authorizes replay or resumption.
"""
from __future__ import annotations

import json
import os
import uuid
from contextlib import nullcontext
from typing import Any

OWNER_RUN_SESSION_PREFIX = 'owner:'
SOURCE = 'resident_owner_request_receipt'


class OwnerReceiptConflict(RuntimeError):
    """Resident proof cannot be safely attributed to the current request."""


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def identity(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in (
        'request_id', 'session_id', 'turn_id', 'digest', 'digest_version',
        'execution_json', 'input_text', 'created_at',
    )}




def stable_agent_assignment(metadata: dict[str, Any]) -> bool:
    """The existing Gateway triage has committed, or this assignment is pinned."""
    return bool(metadata.get('route_checked') or metadata.get('home') or metadata.get('agent_pinned'))


def session_agent_identity(session_id: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Read the canonical assignment without creating agents or trusting request markers."""
    from .session_store import _session_agent
    from jaeger_ai.core.agent_registry import AgentRegistry
    agent_id = _session_agent(session_id, metadata)
    if not agent_id:
        return None
    try:
        agent = AgentRegistry().get_agent(agent_id, read_only=True)
    except (ValueError, TypeError, OSError):
        agent = None  # Malformed registry state cannot escape the dispatch fence.
    if agent is None or agent.id != agent_id:
        return {'id': agent_id, 'kind': None, 'role': None, 'disabled': True}
    return {'id': agent.id, 'kind': agent.kind.value, 'role': agent.role.value,
            'disabled': agent.disabled}


def check_agent_identity(conn: Any, row: Any) -> None:
    if row is None:
        raise OwnerReceiptConflict('Missing admitted agent identity')
    execution = json.loads(row['execution_json'] or '{}')
    if '_owner_agent' not in execution:
        return  # Historical admissions never acquire a new identity.
    session = conn.execute('SELECT metadata_json FROM sessions WHERE session_id=?', (row['session_id'],)).fetchone()
    metadata = json.loads(session['metadata_json']) if session else {}
    actual = session_agent_identity(row['session_id'], metadata) if session else None
    if (not stable_agent_assignment(metadata) or actual != execution['_owner_agent']
            or not actual or actual['disabled'] or not actual['kind'] or not actual['role']):
        raise OwnerReceiptConflict('Admitted agent identity changed or is unavailable')


def canonical_lead(identity: Any) -> bool:
    from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
    from jaeger_ai.core.agent_registry.types import AgentKind, AgentRole
    return identity == {'id': LEAD_AGENT_ID, 'kind': AgentKind.NATIVE.value,
                        'role': AgentRole.LEAD.value, 'disabled': False}

def migrate(conn: Any) -> None:
    conn.execute('CREATE TABLE IF NOT EXISTS owner_request_journal ('
                 'request_id TEXT PRIMARY KEY REFERENCES client_requests(request_id) ON DELETE CASCADE, '
                 'producer_token TEXT NOT NULL, lease_pid INTEGER NOT NULL, lease_started_at REAL NOT NULL, '
                 'identity_json TEXT NOT NULL, native_runs_json TEXT NOT NULL, terminal_json TEXT)')


def _lease(conn: Any, pid: int, started_at: float) -> None:
    row = conn.execute('SELECT * FROM process_lease WHERE id=1').fetchone()
    if row is None or pid != os.getpid() or row['owner_pid'] != pid or row['started_at'] != started_at:
        raise OwnerReceiptConflict('Resident producer no longer owns the Gateway lease')


def _bound(row: Any, journal: Any) -> None:
    if row is None or encoded(identity(row)) != journal['identity_json']:
        raise OwnerReceiptConflict('Resident request authority or identity changed')


def begin(store: Any, request_id: str, session_id: str, lease: dict[str, Any]) -> str:
    token = uuid.uuid4().hex
    with store._immediate() as conn:
        _lease(conn, lease['owner_pid'], lease['started_at'])
        row = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (request_id,)).fetchone()
        if (row is None or row['session_id'] != session_id or row['digest_version'] != 2
                or row['status'] not in {'admitted', 'running'} or row['native_run_id']):
            raise OwnerReceiptConflict('Request is not a fresh resident admission')
        if conn.execute('SELECT 1 FROM owner_request_journal WHERE request_id=?', (request_id,)).fetchone():
            raise OwnerReceiptConflict('Resident request already has a producer; never replay')
        check_agent_identity(conn, row)
        conn.execute('INSERT INTO owner_request_journal VALUES (?, ?, ?, ?, ?, ?, NULL)',
                     (request_id, token, lease['owner_pid'], lease['started_at'], encoded(identity(row)), '[]'))
    return token


def accept(conn: Any, row: Any, run_id: str, native_session: str, token: str | None, reuse_guard=None) -> None:
    journal = conn.execute('SELECT * FROM owner_request_journal WHERE request_id=?', (row['request_id'],)).fetchone()
    if native_session.startswith(OWNER_RUN_SESSION_PREFIX):
        sources = conn.execute(
            'SELECT j.request_id, j.identity_json, j.native_runs_json, j.terminal_json, r.status, r.result_json, r.native_run_id '
            'FROM owner_request_journal j JOIN client_requests r ON r.request_id=j.request_id, '
            'json_each(j.native_runs_json) WHERE j.request_id<>? AND json_each.value=?',
            (row['request_id'], run_id)).fetchall()
        allowed_sources = reuse_guard(conn, row) if sources and journal is None and reuse_guard is not None else set()
        for source in sources:
            original = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (source['request_id'],)).fetchone()
            _bound(original, source)
            check_agent_identity(conn, original)
            # Only the existing TaskOwner's canonical transfer guard can share
            # an UNSEALED yielded run. A sealed request never relinquishes it.
            if (journal is not None or source['request_id'] not in allowed_sources
                    or source['terminal_json'] is not None or source['status'] != 'completed'
                    or json.loads(source['result_json'] or '{}').get('halt_reason') != 'yielded'
                    or source['native_run_id'] != run_id
                    or json.loads(source['native_runs_json'])[-1:] != [run_id]
                    or original['native_session'] != OWNER_RUN_SESSION_PREFIX + original['session_id']):
                raise OwnerReceiptConflict('Native run already belongs to another resident request')
    if journal is None:
        if token is not None:
            raise OwnerReceiptConflict('Missing resident producer journal')
        return
    _bound(row, journal)
    check_agent_identity(conn, row)
    _lease(conn, journal['lease_pid'], journal['lease_started_at'])
    if (not token or token != journal['producer_token'] or journal['terminal_json'] is not None
            or row['status'] not in {'admitted', 'running', 'awaiting_approval'}
            or native_session != OWNER_RUN_SESSION_PREFIX + row['session_id'] or not run_id):
        raise OwnerReceiptConflict('Late, foreign or cancelled resident run binding')
    if conn.execute('SELECT 1 FROM client_requests WHERE request_id<>? AND native_run_id=? LIMIT 1',
                    (row['request_id'], run_id)).fetchone():
        raise OwnerReceiptConflict('Native run already bound to another request')
    runs = json.loads(journal['native_runs_json'])
    if run_id not in runs:
        runs.append(run_id)
        conn.execute('UPDATE owner_request_journal SET native_runs_json=? WHERE request_id=?',
                     (encoded(runs), row['request_id']))
    elif runs[-1] != run_id:
        raise OwnerReceiptConflict('An earlier resident run cannot replace the current run')


def accepted_runs(store: Any, request_id: str, token: str) -> list[str]:
    with store._get_conn() as conn:
        row = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (request_id,)).fetchone()
        journal = conn.execute('SELECT * FROM owner_request_journal WHERE request_id=?', (request_id,)).fetchone()
        if journal is None or journal['producer_token'] != token or journal['terminal_json'] is not None:
            raise OwnerReceiptConflict('Missing or settled resident producer')
        _bound(row, journal)
        check_agent_identity(conn, row)
        _lease(conn, journal['lease_pid'], journal['lease_started_at'])
        return json.loads(journal['native_runs_json'])


def producer_in_transaction(conn: Any, request_id: str, token: str, runs: list[str], *, returned_cancelled: bool = False):
    row = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (request_id,)).fetchone()
    journal = conn.execute('SELECT * FROM owner_request_journal WHERE request_id=?', (request_id,)).fetchone()
    if journal is None or journal['producer_token'] != token:
        raise OwnerReceiptConflict('Foreign resident producer')
    _bound(row, journal)
    check_agent_identity(conn, row)
    _lease(conn, journal['lease_pid'], journal['lease_started_at'])
    allowed = {'admitted', 'running', 'awaiting_approval'} | ({'cancelling'} if returned_cancelled else set())
    if (not runs or row['status'] not in allowed
            or json.loads(journal['native_runs_json']) != runs
            or row['native_run_id'] != runs[-1]
            or row['native_session'] != OWNER_RUN_SESSION_PREFIX + row['session_id']):
        raise OwnerReceiptConflict('Resident producer lost its request binding')
    return row, journal


def finish(store: Any, request_id: str, token: str, runs: list[str], *, status: str,
           result: dict[str, Any], assistant_text: str | None, session_status: str,
           follow_ups: list[str] | None, conn=None, returned_cancelled: bool = False) -> dict[str, Any]:
    """Commit proof after the producer checked quiescence and ALL run effects.

    Runs are compared under the write lock to reject an unexpected late binding.
    Serialization is strict and happens before any proof can become durable.
    """
    if (status not in {'completed', 'failed', 'cancelled'} or not runs
            or (status == 'cancelled') != returned_cancelled):
        raise OwnerReceiptConflict('No qualified returned resident outcome')
    snapshot = {'status': status, 'result': result, 'assistant_text': assistant_text,
                'session_status': session_status, 'follow_ups': follow_ups}
    encoded(snapshot)
    if conn is not None and not conn.in_transaction:
        raise OwnerReceiptConflict('Receipt requires an active owner transaction')
    with (nullcontext(conn) if conn is not None else store._immediate()) as connection:
        row, journal = producer_in_transaction(connection, request_id, token, runs, returned_cancelled=returned_cancelled)
        if result.get('status') != status or result.get('turn_id') != row['turn_id']:
            raise OwnerReceiptConflict('Resident outcome does not name its canonical request turn')
        proof = {**snapshot, 'source': SOURCE, 'version': 1, 'execution_unknown': False,
                 'request_id': request_id, 'session_id': row['session_id'], 'turn_id': row['turn_id'],
                 'native_run_id': row['native_run_id'], 'native_session': row['native_session'],
                 'native_run_ids': runs, 'effects_settled': True}
        serialized = encoded(proof)
        if journal['terminal_json'] is not None and journal['terminal_json'] != serialized:
            raise OwnerReceiptConflict('Resident terminal proof is immutable')
        connection.execute('UPDATE owner_request_journal SET terminal_json=? WHERE request_id=?',
                     (serialized, request_id))
    return proof


def read(conn: Any, row: Any) -> dict[str, Any] | None:
    journal = conn.execute('SELECT * FROM owner_request_journal WHERE request_id=?', (row['request_id'],)).fetchone()
    if journal is None or journal['terminal_json'] is None:
        return None
    _bound(row, journal)
    check_agent_identity(conn, row)
    proof = json.loads(journal['terminal_json'])
    runs = json.loads(journal['native_runs_json'])
    if (not runs or proof.get('native_run_ids') != runs or proof.get('source') != SOURCE
            or proof.get('version') != 1 or proof.get('execution_unknown') is not False
            or proof.get('effects_settled') is not True or proof.get('status') not in {'completed', 'failed', 'cancelled'}
            or proof.get('request_id') != row['request_id'] or proof.get('session_id') != row['session_id']
            or proof.get('turn_id') != row['turn_id'] or proof.get('native_run_id') != row['native_run_id']
            or proof.get('native_session') != row['native_session'] or row['native_run_id'] != runs[-1]
            or row['native_session'] != OWNER_RUN_SESSION_PREFIX + row['session_id']
            or proof.get('result', {}).get('status') != proof['status']
            or proof.get('result', {}).get('turn_id') != row['turn_id']):
        raise OwnerReceiptConflict('Invalid resident request proof')
    return proof
