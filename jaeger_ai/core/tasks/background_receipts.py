"""Returned, independently verified default-background outcomes; never replay.

Separate from foreground receipts: a durable native may remain active after a
returned slice. Neither that state nor an empty effect ledger proves completion.
Only the awaited resident producer may seal its final output, after the task
owner verifies the artifacts and every accepted run has settled effects. Tasks
with delegated children remain outside this bounded recovery contract.
"""
import hashlib
import json
import os
import uuid
from dataclasses import asdict

from jaeger_ai.core.gateway.owner_receipts import (
    OwnerReceiptConflict, _lease, canonical_lead, encoded, identity,
)
from .background_admission import authority, receipt_error, validate_session_metadata
from .models import DurableTask

SOURCE = 'background_owner_terminal_receipt'


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS background_request_journal (
        request_id TEXT PRIMARY KEY REFERENCES client_requests(request_id) ON DELETE CASCADE,
        producer_token TEXT NOT NULL, identity_json TEXT NOT NULL,
        admission_json TEXT NOT NULL, agent_json TEXT NOT NULL,
        terminal_json TEXT, terminal_sha256 TEXT, revoked INTEGER NOT NULL DEFAULT 0)''')


def migrate_native_enrollment(conn):
    # Only future guarded native binds write this record. Historical task JSON
    # is never backfilled into producer authority during an upgrade.
    conn.execute("""CREATE TABLE IF NOT EXISTS background_native_enrollments (
        request_id TEXT PRIMARY KEY,
        identity_json TEXT NOT NULL, admission_json TEXT NOT NULL,
        native_runs_json TEXT NOT NULL)""")


def _admission(task, rid):
    # Native identities are added only by the existing transactional binder.
    return {k: v for k, v in task.payload['background_admissions'][rid].items()
            if k not in {'native_run_id', 'native_session', 'native_run_ids'}}


def _bound(conn, row, journal):
    if (row is None or journal['revoked'] or row['status'] in {'cancelling', 'cancelled'}
            or encoded(identity(row)) != journal['identity_json']):
        raise OwnerReceiptConflict('Background request identity or authority changed')
    rid, sid = row['request_id'], row['session_id']
    raw = conn.execute('SELECT task_json FROM durable_tasks WHERE task_id=?', (sid[5:],)).fetchone()
    task = DurableTask.from_dict(json.loads(raw[0])) if raw and sid.startswith('task:') else None
    if (task is None or task.payload.get('background_admission_version') != 1
            or task.cancellation or not task.provenance.get('authorized')
            or task.state.value in {'cancelled', 'failed', 'needs_owner', 'blocked'}
            or rid != f'{task.task_id}:{task.payload.get("attempt", 0)}'
            or authority(task) != task.payload.get('background_authority')
            or encoded(_admission(task, rid)) != journal['admission_json']
            or encoded(task.payload.get('background_agent')) != journal['agent_json']):
        raise OwnerReceiptConflict('Background producer lost its immutable task admission')
    session = conn.execute('SELECT metadata_json FROM sessions WHERE session_id=?', (sid,)).fetchone()
    metadata = json.loads(session[0]) if session else {}
    validate_session_metadata(task, metadata)
    from jaeger_ai.core.gateway.owner_receipts import session_agent_identity
    actual = session_agent_identity(sid, metadata)
    if actual != task.payload['background_agent'] or not canonical_lead(actual):
        raise OwnerReceiptConflict('Background admitted agent changed')
    reason = receipt_error(task, {**dict(row), 'execution': json.loads(row['execution_json'])})
    if reason:
        raise OwnerReceiptConflict(reason)
    return task


def begin(owner, request_id):
    store = owner.gateway.store
    with store._immediate() as conn:
        row = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (request_id,)).fetchone()
        task = owner.background_dispatch_guard(conn, store._request_row(row)) if row else None
        if task is None:
            raise OwnerReceiptConflict('No canonical background admission')
        admission = _admission(task, request_id)
        if (admission['lease'] != owner.gateway._owner_receipt_lease
                or row['status'] not in {'admitted', 'running'}
                or conn.execute('SELECT 1 FROM owner_request_journal WHERE request_id=?', (request_id,)).fetchone()
                or conn.execute('SELECT 1 FROM background_request_journal WHERE request_id=?', (request_id,)).fetchone()):
            raise OwnerReceiptConflict('Background request already dispatched or has a stale lease; no replay')
        token = uuid.uuid4().hex
        conn.execute('INSERT INTO background_request_journal '
            '(request_id, producer_token, identity_json, admission_json, agent_json) VALUES (?, ?, ?, ?, ?)',
            (request_id, token, encoded(identity(row)), encoded(admission), encoded(task.payload['background_agent'])))
        return token


def assert_open(conn, row):
    journal = conn.execute('SELECT * FROM background_request_journal WHERE request_id=?', (row['request_id'],)).fetchone()
    if journal:
        raw = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (row['request_id'],)).fetchone()
        _bound(conn, raw, journal)
        lease = json.loads(journal['admission_json'])['lease']
        _lease(conn, lease['owner_pid'], lease['started_at'])
        if journal['terminal_json'] is not None:
            raise OwnerReceiptConflict('Sealed background producer cannot bind another run')


def accept_native(conn, row, native, task):
    """Append only in the guarded owner binding commit, including pre-dispatch.

    A continuation can bind its old root before the resident journal begins.
    Enrollment proves that binding; it does not grant terminal seal eligibility.
    """
    assert_open(conn, row)
    rid = row['request_id']
    raw = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (rid,)).fetchone()
    record = conn.execute('SELECT * FROM background_native_enrollments WHERE request_id=?', (rid,)).fetchone()
    admitted = task.payload['background_admissions'][rid].get('native_run_ids') or []
    captured = json.loads(record['native_runs_json']) if record else []
    if (captured != admitted or (record and
            (record['identity_json'] != encoded(identity(raw)) or record['admission_json'] != encoded(_admission(task, rid))))):
        raise OwnerReceiptConflict('Background native enrollment differs from its producer record')
    if native not in captured:
        captured.append(native)
    conn.execute('INSERT INTO background_native_enrollments (request_id, identity_json, admission_json, native_runs_json) '
                 'VALUES (?, ?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET native_runs_json=excluded.native_runs_json',
                 (rid, encoded(identity(raw)), encoded(_admission(task, rid)), encoded(captured)))


def _settled(owner, task, row, task_runs=None):
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from jaeger_ai.core.entity.runtime import EntityRuntime
    rid = row['request_id']
    contract = task.payload['background_admissions'][rid]
    runs = contract.get('native_run_ids') or []
    if not runs or len(set(runs)) != len(runs) or runs[-1] != row['native_run_id']:
        raise OwnerReceiptConflict('Background result has no exact accepted native runs')
    for native in task_runs or runs:
        run = SqliteRunStore().get(native)
        # Durable natives intentionally stay active until task settlement. A
        # returned producer in this lease, not lifecycle inference, is the proof.
        if (run is None or run.owner_pid not in {None, os.getpid()}
                or run.state not in {'active', 'running', 'verifying', 'completed'}
                or (run.state != 'completed' and run.owner_pid != os.getpid())
                or EntityRuntime.run_has_indeterminate_effects(native)):
            raise OwnerReceiptConflict('Background native work is unsettled or foreign')
    if owner._background_children_unsettled(owner.gateway.store._request_row(row)):
        raise OwnerReceiptConflict('Background owned children remain unsettled')
    return runs


def _native_evidence(conn, task, runs):
    """Stable operation fingerprints, with a veto for incompatible lifecycle."""
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
    from jaeger_ai.core.gateway.owner_receipts import protected_background_sources
    evidence = []
    effects = SqliteEffectLedger().list()
    for native in runs:
        run = SqliteRunStore().get(native)
        checkpoint = SqliteRunStore().latest_checkpoint(native)
        if run is None or checkpoint is None:
            raise OwnerReceiptConflict('Missing accepted background operation evidence')
        from jaeger_ai.core.gateway.session_store import pid_is_alive
        if (run.state not in {'active', 'running', 'verifying', 'completed'}
                or (run.owner_pid not in {None, os.getpid()} and pid_is_alive(run.owner_pid))):
            raise OwnerReceiptConflict('Accepted background native cannot safely settle as completed')
        sources = protected_background_sources(conn, native)
        for tid, rid in sources:
            raw = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (rid,)).fetchone()
            if (tid != task.task_id or raw is None or receipt_error(task,
                    {**dict(raw), 'execution': json.loads(raw['execution_json'])})):
                raise OwnerReceiptConflict('Background native evidence belongs to a foreign admission')
        if conn.execute('SELECT 1 FROM client_requests WHERE native_run_id=? AND request_id NOT IN ('
                        + ','.join('?' for _ in sources) + ')',
                        (native, *(rid for _, rid in sources))).fetchone():
            raise OwnerReceiptConflict('Background native evidence has a foreign request alias')
        if conn.execute('SELECT 1 FROM owner_request_journal j, json_each(j.native_runs_json) runs WHERE runs.value=?',
                        (native,)).fetchone():
            raise OwnerReceiptConflict('Background native evidence belongs to a foreground producer')
        owned_effects = sorted((asdict(effect) for effect in effects if effect.run_id == native), key=lambda e: e['key'])
        if any(effect['status'] == 'pending' for effect in owned_effects):
            raise OwnerReceiptConflict('Background operation outcome remains indeterminate')
        evidence.append({'run': {key: getattr(run, key) for key in
            ('id', 'commitment_id', 'attempt', 'provider', 'created_at', 'parent_run_id', 'root_run_id', 'relation')},
            'payload_sha256': hashlib.sha256(encoded(run.payload).encode()).hexdigest(),
            'checkpoint_sha256': hashlib.sha256(encoded(asdict(checkpoint)).encode()).hexdigest(),
            'effects_sha256': hashlib.sha256(encoded(owned_effects).encode()).hexdigest()})
    return evidence


def _task_scope(conn, task, *, require_enrollment=False):
    """Retain every earlier attempt's ownership, not only its final native."""
    runs, references = [], []
    admissions = task.payload['background_admissions']
    prefix = task.task_id + ':'
    prior_requests = {row[0] for row in conn.execute('SELECT request_id FROM client_requests WHERE session_id=?', ('task:'+task.task_id,))
                      if row[0].startswith(prefix) and row[0][len(prefix):].isdigit()
                      and int(row[0][len(prefix):]) <= task.payload.get('attempt', 0)}
    if prior_requests != set(admissions):
        raise OwnerReceiptConflict('Background retained request graph is incomplete')
    for rid, admission in task.payload['background_admissions'].items():
        row = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (rid,)).fetchone()
        if (row is None or admission['attempt'] > task.payload.get('attempt', 0)
                or receipt_error(task, {**dict(row), 'execution': json.loads(row['execution_json'])})):
            raise OwnerReceiptConflict('Background retained attempt ownership is unavailable')
        journal = conn.execute('SELECT * FROM background_request_journal WHERE request_id=?', (rid,)).fetchone()
        enrollment = conn.execute('SELECT * FROM background_native_enrollments WHERE request_id=?', (rid,)).fetchone()
        captured = json.loads(enrollment['native_runs_json']) if enrollment else None
        if ((require_enrollment and captured is None)
                or (captured is not None and (captured != (admission.get('native_run_ids') or [])
                    or enrollment['identity_json'] != encoded(identity(row))
                    or enrollment['admission_json'] != encoded(_admission(task, rid))))
                or (journal and (encoded(_admission(task, rid)) != journal['admission_json']
                                 or encoded(identity(row)) != journal['identity_json']))):
            raise OwnerReceiptConflict('Background retained native enrollment is missing or changed')
        references.extend((rid, row['turn_id']))
        runs.extend(admission.get('native_run_ids') or [])
    runs = list(dict.fromkeys(runs))
    return runs, list(dict.fromkeys([*references, *runs]))


def _validate_root_lineage(native, accepted):
    for run_id in accepted:
        run = native.get(run_id)
        # Actual owner continuation reuses or rotates accepted root runs.
        # An accepted callback does not convert a delegate or foreign lineage
        # into that contract. Parent links wholly inside the accepted root
        # trajectory are not an unaccepted delegated child.
        if (run is None or run.relation != 'root'
                or (run.root_run_id and run.root_run_id not in accepted)):
            raise OwnerReceiptConflict('Background accepted root lineage is incomplete or foreign')
        seen = set()
        while run is not None:
            if run.id in seen or run.id not in accepted:
                raise OwnerReceiptConflict('Background accepted root lineage is incomplete or foreign')
            seen.add(run.id)
            if not run.parent_run_id:
                break
            run = native.get(run.parent_run_id)
            if run is None:
                raise OwnerReceiptConflict('Background accepted root lineage is incomplete or foreign')


def _has_children(conn, references, runs):
    # No delegated tree is eligible in this bounded slice, including historical
    # relationships that cannot be recursively qualified from owner receipts.
    slots = ','.join('?' for _ in references)
    if conn.execute('SELECT 1 FROM handoffs WHERE parent_run_id IN (' + slots
        + ") OR json_extract(metadata_json, '$.parent_binding.request_id') IN (" + slots + ') LIMIT 1',
        (*references, *references)).fetchone():
        return True
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    native = {run.id: run for run in SqliteRunStore().list()}
    accepted = set(runs)
    _validate_root_lineage(native, accepted)
    # root_run_id catches a deeper descendant even when its immediate parent
    # is outside the accepted IDs or its historical parent row is missing.
    return any(run.id not in accepted and
        (run.parent_run_id in accepted or run.root_run_id in accepted)
        for run in native.values())



def assert_settlement_safe(conn, owner, task, *, require_enrollment=False):
    """Qualify one completion graph before normal settlement or producer seal.

    For older no-journal tasks this is only a negative veto, never new replay or
    seal authority. Bound child requests contribute their own native roots even
    when those roots have no native parent link to this task.
    """
    runs, references = _task_scope(conn, task, require_enrollment=require_enrollment)
    evidence = _native_evidence(conn, task, runs)
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
    from jaeger_agent.cognition.lifecycle import TERMINAL
    from jaeger_ai.core.gateway.handoff_ownership import child_receipt
    handoffs = [owner.gateway.store._handoff_row(row) for row in conn.execute('SELECT * FROM handoffs')]
    references, seen, child_roots = set(references), set(), set()
    while True:
        linked = [record for record in handoffs if record['id'] not in seen and
                  (record.get('parent_run_id') in references or
                   (record.get('metadata') or {}).get('parent_binding', {}).get('request_id') in references)]
        if not linked:
            break
        for record in linked:
            seen.add(record['id'])
            _, _, child, bound = child_receipt(owner.gateway, record)
            if child is None and (record.get('metadata') or {}).get('cancelled_before_admission') is True:
                continue
            if child is None or not bound or child['status'] not in {'completed', 'failed', 'cancelled'}:
                raise OwnerReceiptConflict('Background child request graph is incomplete or unresolved')
            references.update((child['request_id'], child['turn_id']))
            if str(child.get('native_session') or '').startswith('owner:'):
                native = child.get('native_run_id')
                if not native or native in runs:
                    raise OwnerReceiptConflict('Background child native identity is missing or aliases its parent')
                enrolled = {native}
                for table in ('owner_request_journal', 'background_native_enrollments'):
                    row = conn.execute('SELECT native_runs_json FROM '+table+' WHERE request_id=?', (child['request_id'],)).fetchone()
                    if row:
                        if row[0] is None or native not in json.loads(row[0]):
                            raise OwnerReceiptConflict('Background child native enrollment is incomplete')
                        enrolled.update(json.loads(row[0]))
                child_roots.update(enrolled)
                references.update(enrolled)
    native = {run.id: run for run in SqliteRunStore().list()}
    _validate_root_lineage(native, set(runs))
    owned = set(runs) | child_roots
    while True:
        added = {run.id for run in native.values() if run.parent_run_id in owned or run.root_run_id in owned} - owned
        if not added:
            break
        owned.update(added)
    for ident in owned - set(runs):
        run = native.get(ident)
        if run is None or run.state not in TERMINAL or SqliteRunStore().latest_checkpoint(ident) is None:
            raise OwnerReceiptConflict('Background native child graph is incomplete or unresolved')
    if any(effect.run_id in owned and effect.status == 'pending' for effect in SqliteEffectLedger().list()):
        raise OwnerReceiptConflict('Background completion graph has unresolved operations')
    return evidence


def finish(owner, request_id, token, result, assistant_text, follow_ups):
    """Only the Gateway's awaited resident-return branch calls this function."""
    if (result.get('status') != 'completed' or result.get('error') or result.get('halt_reason')
            or not isinstance(assistant_text, str) or not assistant_text.strip()
            or result.get('output') != assistant_text):
        return False  # Yielded/blocked/empty/failed results never gain completion proof.
    store = owner.gateway.store
    with store._immediate() as conn:
        row = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (request_id,)).fetchone()
        journal = conn.execute('SELECT * FROM background_request_journal WHERE request_id=?', (request_id,)).fetchone()
        if journal is None or journal['producer_token'] != token or journal['terminal_json'] is not None:
            raise OwnerReceiptConflict('Missing, foreign or settled background producer')
        task = _bound(conn, row, journal)
        owner.background_dispatch_guard(conn, store._request_row(row))
        lease = json.loads(journal['admission_json'])['lease']
        _lease(conn, lease['owner_pid'], lease['started_at'])
        if (lease != owner.gateway._owner_receipt_lease or task.is_terminal
                or row['status'] not in {'admitted', 'running'}
                or result.get('turn_id') != row['turn_id']):
            raise OwnerReceiptConflict('Background outcome differs from its live producer')
        runs = _settled(owner, task, row)
        task_runs, references = _task_scope(conn, task, require_enrollment=True)
        _settled(owner, task, row, task_runs)
        native_evidence = assert_settlement_safe(conn, owner, task, require_enrollment=True)
        # Delegated child recovery is deliberately outside this first slice.
        # A terminal child label alone is not a recursively qualified receipt.
        if _has_children(conn, references, task_runs):
            return False
        checked_result = json.loads(encoded(result))
        verified, evidence = owner.verify(task, checked_result)
        if not verified or not evidence:
            return False
        if 'research_contract' in task.payload:
            # Research verification intentionally replaces worker prose with
            # the exact report bytes it checked. Seal that owner output, without
            # letting the verifier mutate the caller's pending response.
            assistant_text = checked_result['text']
            result = {**checked_result, 'output': assistant_text}
        proof = {'source': SOURCE, 'version': 3, 'status': 'completed',
            'execution_unknown': False, 'effects_settled': True,
            'request_id': request_id, 'session_id': row['session_id'], 'turn_id': row['turn_id'],
            'native_run_id': row['native_run_id'], 'native_session': row['native_session'],
            'native_run_ids': runs, 'admission': task.payload['background_admissions'][request_id],
            'task_native_run_ids': task_runs, 'task_admissions': task.payload['background_admissions'],
            'result': result, 'assistant_text': assistant_text, 'session_status': 'idle',
            'follow_ups': follow_ups, 'verification': evidence, 'native_evidence': native_evidence}
        serialized = encoded(proof)
        # Recheck after independent file/Research verification; cancellation or
        # a changed native binding must never turn into completion authority.
        owner.background_dispatch_guard(conn, store._request_row(row))
        _settled(owner, task, row, task_runs)
        if (_has_children(conn, references, task_runs)
                or _native_evidence(conn, task, task_runs) != native_evidence):
            raise OwnerReceiptConflict('Background operation evidence changed during verification')
        conn.execute('UPDATE background_request_journal SET terminal_json=?, terminal_sha256=? WHERE request_id=?',
            (serialized, hashlib.sha256(serialized.encode()).hexdigest(), request_id))
    return True


def read(conn, row):
    journal = conn.execute('SELECT * FROM background_request_journal WHERE request_id=?', (row['request_id'],)).fetchone()
    if journal is None or journal['terminal_json'] is None:
        return None
    task = _bound(conn, row, journal)
    task_runs, references = _task_scope(conn, task, require_enrollment=True)
    if _has_children(conn, references, task_runs):
        raise OwnerReceiptConflict('Background delegated outcomes need separate reconciliation')
    if hashlib.sha256(journal['terminal_json'].encode()).hexdigest() != journal['terminal_sha256']:
        raise OwnerReceiptConflict('Background terminal snapshot is damaged')
    proof = json.loads(journal['terminal_json'])
    contract = task.payload['background_admissions'][row['request_id']]
    if (proof.get('source') != SOURCE or proof.get('version') != 3 or proof.get('status') != 'completed'
            or proof.get('effects_settled') is not True or proof.get('execution_unknown') is not False
            or proof.get('admission') != contract or proof.get('native_run_ids') != contract.get('native_run_ids')
            or proof.get('task_native_run_ids') != task_runs
            or proof.get('task_admissions') != task.payload['background_admissions']
            or any(proof.get(key) != row[key] for key in
                   ('request_id', 'session_id', 'turn_id', 'native_run_id', 'native_session'))
            or proof.get('result', {}).get('status') != 'completed'
            or proof['result'].get('turn_id') != row['turn_id']
            or proof['result'].get('error') or proof['result'].get('halt_reason')
            or not str(proof.get('assistant_text') or '').strip()
            or proof['result'].get('output') != proof['assistant_text']):
        raise OwnerReceiptConflict('Background terminal snapshot differs from its admitted result')
    # Retained bytes/Research obligations must still match the owner evidence.
    # This is read-only verification, never resumption or another tool call.
    from .owner import GatewayTaskOwner
    checked_result = json.loads(encoded(proof['result']))
    verified, evidence = GatewayTaskOwner.verify(task, checked_result)
    if (not verified or evidence != proof['verification']
            or ('research_contract' in task.payload and checked_result.get('text') != proof['assistant_text'])
            or _has_children(conn, references, task_runs)
            or _native_evidence(conn, task, task_runs) != proof['native_evidence']):
        raise OwnerReceiptConflict('Background verified artifacts changed; inspect without replay')
    return proof
