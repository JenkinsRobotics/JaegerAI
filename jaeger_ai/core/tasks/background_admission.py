"""Owner-issued admission for new client default-lead background tasks.

This is an authority contract, not terminal evidence or permission to replay.
Other existing runners/routes and historical tasks do not acquire this contract.
"""
import json
from pathlib import Path

from jaeger_ai.core.gateway.owner_receipts import canonical_lead, session_agent_identity
from jaeger_ai.core.gateway.session_store import _normalize_requested


def clone(value):
    return json.loads(json.dumps(value))


def authority(task):
    return clone({'task_id': task.task_id, 'session_id': 'task:'+task.task_id,
        'parent_session_id': task.notification_policy.recipient_session_id,
        'goal': task.goal, 'agent_id': task.agent_id, 'runner': task.runner,
        'execution': task.payload['execution'], 'admitted_tier': task.payload.get('background_tier'),
        'artifacts': task.payload.get('artifacts'),
        'research_contract': task.payload.get('research_contract'),
        'research_artifacts': task.payload.get('research_artifacts')})


def prepare(owner, conn, task):
    raw = task.payload['execution']
    # Positive narrow eligibility, not a change to specialist/delegate/provider workflows.
    from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
    if (task.runner != 'native' or task.agent_id not in {'', LEAD_AGENT_ID}
            or raw.get('model') or raw.get('provider') or raw.get('options')
            or raw.get('attachments') or raw.get('attachment_ids') or raw.get('is_subordinate')):
        return
    parent = conn.execute('SELECT * FROM sessions WHERE session_id=?',
        (task.notification_policy.recipient_session_id,)).fetchone()
    if parent is None:
        raise ValueError('Background task originating session is unavailable')
    metadata = json.loads(parent['metadata_json'])
    # A selected parent route is an existing explicit workflow, not this default path.
    if metadata.get('model') or metadata.get('provider'):
        return
    identity = session_agent_identity(parent['session_id'], metadata)
    if not canonical_lead(identity):
        raise ValueError('Default background task requires an enabled canonical lead')
    choices = _normalize_requested({**raw, 'attachment_ids': [],
        'interaction_tier': raw.get('interaction_tier') or owner.gateway._current_tier()})
    execution = owner.gateway.store._resolve_execution(conn, parent['session_id'], choices, metadata, parent['workspace'])
    execution.pop('_owner_agent', None)
    owner.gateway.store._apply_execution_defaults(execution, owner.gateway._foreground_execution_defaults)
    if (not execution.get('model') or not execution.get('provider')
            or not Path(execution.get('workspace') or '').is_absolute()
            or execution.get('interaction_tier') not in {'agent', 'jaeger'}
            or not (execution.get('_instance_defaults') or {}).get('route_fingerprint')):
        raise ValueError('Default background execution scope is unresolved; no task admitted')
    current_tier = owner.gateway._current_tier()
    if current_tier not in {'agent', 'jaeger'} or (current_tier == 'agent' and execution['interaction_tier'] == 'jaeger'):
        raise ValueError('Background requested tier exceeds current authority')
    task.payload['background_tier'] = current_tier
    task.agent_id = identity['id']
    task.payload['execution'] = execution
    task.payload['background_admission_version'] = 1
    task.payload['background_agent'] = identity
    task.payload['background_authority'] = authority(task)
    task.payload['background_objective_version'] = 1


def validate(owner, task, conn=None):
    if task.payload.get('background_admission_version') != 1:
        return
    if authority(task) != task.payload.get('background_authority'):
        raise ValueError('Background task differs from immutable authority')
    execution = task.payload['execution']
    defaults = owner.gateway._foreground_execution_defaults()
    marker = execution.get('_instance_defaults') or {}
    if (defaults.get('route_fingerprint') != marker.get('route_fingerprint')
            or (marker.get('workspace') and defaults.get('workspace') != marker['workspace'])):
        raise ValueError('Background default configuration changed; no dispatch')
    if owner.gateway._current_tier() != task.payload.get('background_tier'):
        raise ValueError('Background interaction tier changed; no dispatch')
    # Read identity without creating or rerouting agents. The pinned child is checked separately.
    actual = session_agent_identity('task:'+task.task_id,
        {'agent_id': task.agent_id, 'agent_pinned': True})
    if actual != task.payload.get('background_agent') or not canonical_lead(actual):
        raise ValueError('Background admitted agent changed; no dispatch')
    if conn is None:
        with owner.gateway.store._get_conn() as connection:
            _validate_session(connection, task)
    else:
        _validate_session(conn, task)


def _validate_session(conn, task):
    row = conn.execute('SELECT metadata_json FROM sessions WHERE session_id=?', ('task:'+task.task_id,)).fetchone()
    metadata = json.loads(row['metadata_json']) if row else {}
    validate_session_metadata(task, metadata)


def validate_session_metadata(task, metadata):
    if (metadata.get('task_id') != task.task_id or metadata.get('agent_id') != task.agent_id
            or not metadata.get('agent_pinned') or not metadata.get('route_checked')
            or metadata.get('execution_mode') != 'agent' or metadata.get('actionable') is not True
            or metadata.get('parent_session_id') != task.notification_policy.recipient_session_id):
        raise ValueError('Background execution session identity changed; no dispatch')



def receipt_error(task, row):
    contract = task.payload.get('background_admissions', {}).get(row.get('request_id'))
    if not contract:
        return 'Background receipt has no exact retained admission; inspect without replay'
    if (authority(task) != task.payload.get('background_authority')
            or contract.get('authority') != task.payload.get('background_authority')
            or contract.get('objective_version') != task.payload.get('background_objective_version')
            or row.get('session_id') != contract['session_id']
            or row.get('input_text') != contract['input_text']
            or row.get('execution') != contract['execution']
            or row.get('digest_version') != 2):
        return 'Background receipt differs from retained task authority; inspect without replay'
    native = row.get('native_run_id')
    if (native != contract.get('native_run_id')
            or row.get('native_session') != contract.get('native_session')
            or (row.get('status') in {'completed', 'failed'} and not native)):
        return 'Background receipt differs from retained native ownership; inspect without replay'
    if native and row.get('native_session') != 'owner:'+contract['session_id']:
        return 'Background receipt differs from retained native session; inspect without replay'
    return None
