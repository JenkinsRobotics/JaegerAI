"""Gateway-owned durable work. A chat turn admits work; it does not own its lifetime.

Dispatch uses the existing Gateway request/effect receipts. The task store is in
that same database; there is no second worker daemon or model-selection path.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from jaeger_ai.core.gateway.session_store import RequestConflict

from .completion import CompletionError, authoritative_transition
from .models import DurableTask, Goal, NotificationPolicy, Receipt, TaskCard, TaskKind, TaskRunRecord, TaskState
from .store import SqliteDurableTaskStore


#: What a worker must return for the owner to call work verified. One definition, used by
#: durable tasks and by turn-owned cards, so the verifier and the worker agree on evidence.
EVIDENCE_CONTRACT = (
    'Use work_ledger with verify={kind: paths_exist, paths: [your result files]} and complete_task. '
    'A count-only ledger or a successful command is not a verified deliverable.'
)


#: What a turn-owned worker is told. It describes the checks the owner really
#: runs (close_turn/verify), so the model works toward evidence instead of a ritual.
TURN_CARD_GUIDANCE = (
    'This request is owned by a task card. After you reply, the owner checks your result '
    'independently: every file the request names is re-read and hashed, and an answer it '
    'cannot check is recorded as unverified for the owner to review. So work in small steps '
    'and check each result with a tool before relying on it (read the file back, run the '
    'test, list the directory). If a tool fails, read the error, fix the cause and retry. '
    'Take more steps rather than guess. Report only what you checked, and say plainly what '
    'you could not do. For multi-item work you may also: ' + EVIDENCE_CONTRACT
)


#: The owner found nothing it can check deterministically (no declared artifact,
#: no file receipt, no named file). Turn cards with only this go to needs_owner.
UNVERIFIABLE = 'No objective verification receipt; continue execution and verify the result'


def _asserts_success(result: dict) -> bool:
    """The worker claimed completion (complete_task, a dispatched worker's own
    "completed", or state/verification fields)."""
    return bool(result.get('task_completion')) or any(
        k in result for k in ('state', 'task_state', 'verification', 'worker_state'))


def has_file_receipt(completion: dict | None) -> bool:
    """True when a completion carries a receipt for a file the owner can re-check."""
    receipts = (completion or {}).get('verification_receipts') or []
    return bool((completion or {}).get('ok')) and any(r.get('kind') == 'file_sha256' for r in receipts)


def background_requested(text: str) -> bool:
    body = ' '.join((text or '').split())
    if re.match(r'(?i)^(what|why|how|which|explain|tell me)\b', body):
        return False
    return bool(re.search(r'(?i)\b(queue|schedule|delegate|background|deep[ -]think)\b', body))


class TaskAdmissionChanged(ValueError):
    """Saved task authority changed before its request could be committed."""


class GatewayTaskOwner:
    def __init__(self, gateway):
        self.gateway = gateway
        self.store = SqliteDurableTaskStore(gateway.store.path)
        self._loop_task = None
        self._active: dict[str, asyncio.Task] = {}
        self._stopping = False
        # Results kept because their parent session is gone. Logged once each: the
        # 1 s tick otherwise rewrote the same warning forever (500k+ lines live).
        self._retained: set[str] = set()

    @staticmethod
    def artifact_paths(workspace: str, artifacts: list[str] | None) -> list[str]:
        """Declared deliverables, resolved and confined to the admitted workspace."""
        paths = []
        for raw in artifacts or []:
            if not workspace:
                raise ValueError('Artifact verification requires an admitted workspace')
            root = Path(workspace).expanduser().resolve()
            path = Path(raw).expanduser()
            path = (root / path).resolve() if not path.is_absolute() else path.resolve()
            if not path.is_relative_to(root):
                raise ValueError('Artifact lies outside the admitted workspace')
            paths.append(str(path))
        return sorted(set(paths))

    def submit(self, goal: str, *, context: dict, artifacts: list[str] | None = None,
               proposal: bool = False, key: str = '', workflow_reference: dict | None = None, research_contract: dict | None = None, canonical_background: bool = False) -> dict:
        if research_contract is not None:
            from .research import validate_contract
            if context.get('source') != 'client':
                raise ValueError('Research contract requires explicit client admission')
            research_contract = validate_contract(research_contract)
        workflow_provenance = {}
        if workflow_reference is not None:
            if (not isinstance(workflow_reference, dict) or set(workflow_reference) != {'id', 'revision', 'digest'}
                    or not isinstance(workflow_reference['id'], str) or not workflow_reference['id']
                    or type(workflow_reference['revision']) is not int or workflow_reference['revision'] < 1
                    or not isinstance(workflow_reference['digest'], str)
                    or re.fullmatch(r'[0-9a-f]{64}', workflow_reference['digest']) is None):
                raise ValueError('Exact saved workflow reference required')
            workflow_provenance = {'workflow_' + key: value for key, value in workflow_reference.items()}
        goal = goal.strip()
        if not goal:
            raise ValueError('Task objective is required')
        parent = str(context.get('session_id') or '')
        if not parent or not self.gateway.store.get_session(parent):
            raise ValueError('Task requires an existing originating session')
        execution = dict(context.get('execution') or {})
        execution.pop('attachment_ids', None)
        execution.pop('attachments', None)
        # Source authorization is installed by the owner, not a model argument.
        authorized = context.get('source') == 'user' and background_requested(context.get('user_text', ''))
        approved = authorized or (not proposal and context.get('source') == 'client')
        workspace = str(execution.get('workspace') or '')
        paths = self.artifact_paths(workspace, artifacts)
        submission_id = context.get('client_submission_id')
        if submission_id is not None and not isinstance(submission_id, str):
            raise ValueError('Client submission ID must be text')
        identity = ('client:' + submission_id) if submission_id else key or json.dumps([context.get('request_id') or '', ' '.join(goal.casefold().split())])
        tid = 'task_' + hashlib.sha256(json.dumps([parent, identity]).encode()).hexdigest()[:24]
        research_artifacts = None
        if research_contract is not None:
            from .research import artifact_paths
            research_artifacts = artifact_paths(tid)
        # Client identity describes the original choices, not later resolved
        # defaults. Only newly qualified tasks persist this without a nonce.
        candidate_fingerprint = hashlib.sha256(json.dumps({'goal': goal, 'execution': execution, 'artifacts': paths,
            'proposal': proposal, 'agent_id': context.get('agent_id') or '', 'eta': context.get('eta'),
            'runner': context.get('runner') or 'native', **({'research_contract': research_contract, 'research_artifacts': research_artifacts} if research_contract is not None else {})}, sort_keys=True).encode()).hexdigest()
        fingerprint = None
        if submission_id:
            from .store import TaskConflict
            if not isinstance(submission_id, str) or len(submission_id) > 128:
                raise ValueError('Client submission ID must be text of at most128 characters')
            fingerprint = candidate_fingerprint
            matches = self.store.client_submissions(parent, submission_id)
            if len(matches) > 1:
                raise TaskConflict('Multiple legacy tasks share this submission identity; inspect them without replay')
            if matches:
                previous = matches[0]
                previous_fingerprint = previous.provenance.get('submission_fingerprint')
                same = previous_fingerprint == fingerprint if previous_fingerprint else (previous.goal == goal and previous.payload.get('execution') == execution and previous.payload.get('artifacts') == paths and previous.agent_id == str(context.get('agent_id') or '') and previous.runner == str(context.get('runner') or 'native') and previous.eta == context.get('eta') and previous.payload.get('research_contract') == research_contract)
                if not same:
                    raise TaskConflict('Client submission identity conflicts with admitted work')
                return {'ok': True, 'task_id': previous.task_id, 'status': previous.state.value, 'replayed': True,
                        'session_id': f'task:{previous.task_id}', 'authorized': previous.provenance.get('authorized', False)}
        payload = {'execution': execution, 'artifacts': paths}
        if research_contract is not None:
            payload['research_contract'] = research_contract
            payload['research_artifacts'] = research_artifacts
        task = DurableTask(tid, 'native:jaeger', goal, kind=TaskKind.LONG_RUNNING,
            state=TaskState.QUEUED if approved else TaskState.PAUSED, payload=payload,
            notification_policy=NotificationPolicy(recipient_session_id=parent),
            provenance={'request_id': context.get('request_id'), 'authorized': approved,
                        'source': context.get('source'), 'session_id': parent, **workflow_provenance, **({'submission_fingerprint': fingerprint, 'submission_goal': goal} if fingerprint else {})},
            agent_id=str(context.get('agent_id') or ''), eta=context.get('eta'),
            runner=str(context.get('runner') or 'native'))
        if canonical_background:
            if context.get('source') != 'client':
                raise ValueError('Canonical background admission requires explicit client intent')
            from .background_admission import prepare
            with self.gateway.store._immediate() as conn:
                # Replay was checked above; never upgrade an existing task.
                existing = self.store.get_task_in_transaction(conn, tid)
                if existing is None:
                    prepare(self, conn, task)
                    if task.payload.get('background_admission_version') == 1 and not fingerprint:
                        task.provenance.update(submission_fingerprint=candidate_fingerprint, submission_goal=goal)
                elif (existing.payload.get('background_admission_version') == 1
                      and existing.provenance.get('submission_fingerprint') and not fingerprint):
                    # Exact replay compares retained raw-input identity, without
                    # rereading changed defaults or upgrading unmarked history.
                    task.provenance.update(submission_fingerprint=candidate_fingerprint, submission_goal=goal)
                task, replayed = self.store.admit_task_in_transaction(conn, task)
        else:
            task, replayed = self.store.admit_task(task)
        if not replayed:
            def checkpoint_admission(current):
                current.payload['completion_criteria'] = {
                    'objective': current.goal, 'artifacts': paths,
                    'verification': EVIDENCE_CONTRACT,
                }
                self._checkpoint(current, {})
            task = self.store.update_task(tid, checkpoint_admission)
            self._execution_session(task)
            self.gateway.event_bus.publish(parent, 'task.created', {'task': task.to_dict()})
            if not approved:
                approval = self.gateway.store.create_approval(kind='background_task',
                    prompt=f'Run proposed background task: {goal}', options=['once', 'deny'],
                    session_id=parent, metadata={'task_id': tid})
                self.gateway.event_bus.publish(parent, 'approval.request', approval)
        return {'ok': True, 'task_id': tid, 'status': task.state.value, 'replayed': replayed,
                'session_id': f'task:{tid}', 'authorized': task.provenance.get('authorized', False)}

    def propose_inbound(self, conn, *, delivery_id, subscription, goal, execution):
        """Compose a paused task + one approval with the caller's delivery transaction.

        Only an internal validated subscription owner calls this. Incoming data
        supplies neither caller identity nor tools, workspace or approval state.
        """
        tid = 'task_' + hashlib.sha256(('webhook:' + delivery_id).encode()).hexdigest()[:24]
        parent = subscription['session_id']
        task = DurableTask(tid, 'native:jaeger', goal, kind=TaskKind.LONG_RUNNING,
            state=TaskState.PAUSED, payload={'execution': execution, 'artifacts': []},
            agent_id=subscription['agent_id'], notification_policy=NotificationPolicy(recipient_session_id=parent),
            provenance={'source': 'webhook', 'authorized': False, 'session_id': parent,
                        'request_id': delivery_id, 'webhook_subscription_id': subscription['id'],
                        'webhook_revision': subscription['revision'], 'webhook_delivery_id': delivery_id})
        task, replayed = self.store.admit_task_in_transaction(conn, task)
        if replayed:
            raise ValueError('Inbound admission exists without its receipt; inspect without replay')
        approval = self.gateway.store.create_approval(kind='background_task',
            prompt='Review inbound webhook task before running:\n' + goal, options=['once', 'deny'],
            session_id=parent, metadata={'task_id': tid}, approval_id='approval_' + delivery_id,
            connection=conn)
        return task, approval

    def edit_proposal(self, task_id: str, *, goal: str, expected_updated_at: float) -> dict:
        """Edit only an unstarted, unapproved proposal, under the owner's transaction."""
        if not goal.strip():
            raise ValueError("Task objective is required")
        def update(task):
            if task.state is not TaskState.PAUSED or task.provenance.get("authorized") or task.run_history:
                raise ValueError("Only an unstarted proposal can be edited")
            if task.updated_at != expected_updated_at:
                raise ValueError("Task changed; refresh before editing")
            if task.payload.get('background_admission_version') == 1:
                from .background_admission import validate
                validate(self, task)
            task.goal = goal.strip()
            if task.payload.get('background_admission_version') == 1:
                from .background_admission import authority
                task.payload['background_authority'] = authority(task)
                task.payload['background_objective_version'] += 1
            if 'completion_criteria' in task.payload:
                task.payload['completion_criteria']['objective'] = task.goal
            self._checkpoint(task, {})
        task = self.store.update_task(task_id, update)
        parent = task.notification_policy.recipient_session_id
        # Editing invalidates the old decision surface. A stale card must never
        # approve an objective the user has not seen.
        for row in self.gateway.store.list_pending_approvals():
            if (row.get("metadata") or {}).get("task_id") == task_id:
                self.gateway.store.resolve_approval(row["approval_id"], approved=False, decision="deny")
                self.gateway.event_bus.publish(parent, "approval.resolved", {"approval_id": row["approval_id"], "approved": False, "reason": "proposal edited"})
        approval = self.gateway.store.create_approval(kind="background_task",
            prompt=f"Run proposed background task: {task.goal}", options=["once", "deny"],
            session_id=parent, metadata={"task_id": task_id})
        self.gateway.event_bus.publish(parent, "approval.request", approval)
        self.gateway.event_bus.publish(parent, "task.updated", {"task": task.to_dict()})
        return task.to_dict()

    def resolve(self, task_id: str, approved: bool) -> None:
        def update(task):
            if task.is_terminal:
                return
            if task.provenance.get('authorized'):
                # Approval is admission, never permission to replay uncertain effects.
                return
            if approved:
                if task.payload.get('background_admission_version') == 1 and task.cancellation:
                    raise ValueError('Cancelled background authority cannot be approved')
                from .background_admission import validate
                validate(self, task)
            task.provenance['authorized'] = approved
            authoritative_transition(
                task, TaskState.QUEUED if approved else TaskState.CANCELLED, error=None,
            )
            self._checkpoint(task, {})
        task = self.store.update_task(task_id, update)
        self.gateway.event_bus.publish(task.notification_policy.recipient_session_id, 'task.updated', {'task': task.to_dict()})

    def migrate_legacy(self, layout) -> int:
        """Import outstanding board-backed jobs once; retain board cards as projections.

        Explicit authorization is recovered only from the persisted user message
        associated with the card. Unknown old in-flight work is never replayed.
        """
        from jaeger_agent.background.board import board_for_layout
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        board = board_for_layout(layout)
        cfg = load_yaml(layout.config_path, Config)
        count = 0
        # Skill maintenance targets instance-owned skills, regardless of the
        # foreground chat's project. Repair previously imported admission scope;
        # existing request receipts retain their original frozen execution data.
        for task in self.store.list_tasks():
            if (not task.is_terminal and task.provenance.get('source') == 'legacy_import'
                    and task.goal.startswith('[skill-review:')):
                self.store.update_task(task.task_id, lambda t:
                    t.payload['execution'].update(workspace=str(layout.root)))
        for card in board.list(source='deepthink'):
            if card.column == 'done' or 'gateway-owned' in card.tags:
                continue
            parent = None
            user_text = ''
            with self.gateway.store._get_conn() as conn:
                message = conn.execute("SELECT id, session_id, content FROM messages WHERE role='assistant' AND content LIKE ? ORDER BY id DESC LIMIT 1",
                                       ('%' + card.id + '%',)).fetchone()
                if message:
                    parent = self.gateway.store.get_session(message['session_id'])
                    user = conn.execute("SELECT content FROM messages WHERE session_id=? AND role='user' AND id<? ORDER BY id DESC LIMIT 1",
                                        (message['session_id'], message['id'])).fetchone()
                    user_text = user[0] if user else ''
            parent = parent or self.gateway.store.ensure_session('deepthink', title='Background work', profile='jaeger')
            approved = card.column in {'ready', 'in_progress'} or background_requested(user_text)
            # The staged runner increments attempts before executing anything.
            # A board move with zero attempts is not an execution receipt.
            unknown = card.column == 'in_progress' and card.attempts > 0
            key = ' '.join((user_text or card.id).casefold().split())
            tid = 'task_' + hashlib.sha256(json.dumps([parent['session_id'], key]).encode()).hexdigest()[:24]
            existing = self.store.get_task(tid)
            if existing is None:
                workspace = str(layout.root) if card.title.startswith('[skill-review:') else (parent.get('workspace') or str(Path(layout.root) / 'workspace'))
                model = str(getattr(cfg.deep_think, 'coder_model', '') or '')
                execution = {'workspace': workspace, 'model': model,
                             'provider': str(cfg.external_model.provider or '')}
                task = DurableTask(tid, 'native:jaeger', card.title, kind=TaskKind.LONG_RUNNING,
                    state=TaskState.PAUSED if unknown or not approved else TaskState.QUEUED,
                    payload={'execution':execution, 'artifacts':[], 'legacy_cards':[card.id]},
                    notification_policy=NotificationPolicy(recipient_session_id=parent['session_id']),
                    provenance={'source':'legacy_import', 'authorized':approved, 'session_id':parent['session_id'],
                                'legacy_execution_unknown':unknown},
                    error='Legacy execution must be reconciled before replay' if unknown else None)
                self.store.admit_task(task)
            else:
                self.store.update_task(tid, lambda t: t.payload.setdefault('legacy_cards', []).append(card.id)
                                       if card.id not in t.payload.get('legacy_cards', []) else None)
            board.update(card.id, tags=list(set(card.tags + ['gateway-owned'])),
                         notes=f'{card.notes or ""}\nExecution owned by Gateway task {tid}; this card is a history projection.'.strip())
            for related in board.list():
                if (message and related.source == 'agent' and 'deepthink' in related.tags
                        and related.id in message['content']):
                    board.update(related.id, tags=list(set(related.tags + ['gateway-owned'])),
                                 notes=f'{related.notes or ""}\nExecution owned by Gateway task {tid}.'.strip())
                    self.store.update_task(tid, lambda t, cid=related.id:
                        t.payload.setdefault('legacy_cards', []).append(cid)
                        if cid not in t.payload.get('legacy_cards', []) else None)
            count += 1
        pending = {a.get('metadata', {}).get('task_id') for a in self.gateway.store.list_pending_approvals()}
        for task in self.store.list_tasks():
            if (task.state == TaskState.PAUSED and not task.provenance.get('authorized')
                    and task.task_id not in pending and not task.cancellation):
                approval = self.gateway.store.create_approval(kind='background_task',
                    prompt=f'Run proposed background task: {task.goal}', options=['once', 'deny'],
                    session_id=task.notification_policy.recipient_session_id,
                    metadata={'task_id': task.task_id})
                self.gateway.event_bus.publish(task.notification_policy.recipient_session_id,
                                               'approval.request', approval)
        return count

    def admit_turn_card(self, card_payload: dict, *, execution: dict | None = None,
                        artifacts: list[str] | None = None, source: str = 'gateway_turn',
                        resume: bool = False, agent_id: str = '') -> DurableTask:
        """Admit the Goal/TaskCard of a live turn.

        The turn that admits it is also its executor, so the scheduler must not
        run it a second time (``tick`` skips ``turn_owned`` tasks).
        """
        tid = str(card_payload["task_id"])
        parent = str(card_payload["session_id"])
        if not parent or not self.gateway.store.get_session(parent):
            raise ValueError('Task requires an existing originating session')
        task = DurableTask(
            tid, 'native:jaeger', str(card_payload["goal"]),
            kind=TaskKind.LONG_RUNNING, state=TaskState.QUEUED,
            payload={'turn_card': dict(card_payload), 'execution': json.loads(json.dumps(execution or {})),
                     'artifacts': list(artifacts or []),
                     **({'foreground_resume_version': 1, 'original_request_id': card_payload.get('request_id')}
                        if resume else {})},
            agent_id=agent_id,
            notification_policy=NotificationPolicy(recipient_session_id=parent),
            provenance={'authorized': True, 'turn_owned': True, 'source': source,
                        'session_id': parent, 'request_id': card_payload.get('request_id')},
        )
        task, replayed = self.store.admit_task(task)
        if not replayed:
            self.gateway.event_bus.publish(parent, 'task.created', {'task': task.to_dict()})
        return task

    def settle_turn_card(self, task_id: str, state: TaskState, *, evidence: Any = None,
                         error: str | None = None, result: Any = None, conn=None,
                         returned_cancelled: bool = False) -> DurableTask:
        """The one place a turn-owned task changes state.

        Callers hand over evidence; they never assign ``task.state``. A claim of
        ``completed_verified`` without real evidence becomes ``failed`` here, so
        no caller can report verified work it cannot show.
        """
        if returned_cancelled and (conn is None or not conn.in_transaction or state != TaskState.CANCELLED):
            raise ValueError('Confirmed cancellation requires atomic owner finalization')
        def change(task: DurableTask) -> None:
            if task.is_terminal or (task.cancellation and not returned_cancelled):
                return
            if returned_cancelled:
                from jaeger_ai.core.gateway.handoff_cancellation import unconfirmed_ids
                if unconfirmed_ids(task.payload.get('cancellation_children') or []):
                    raise ValueError('Owned children remain unconfirmed')
            try:
                authoritative_transition(task, state, evidence=evidence, error=error)
            except CompletionError as exc:
                authoritative_transition(task, TaskState.FAILED, evidence=evidence, error=str(exc))
            if result is not None:
                task.result = result
        task = (self.store.update_task_in_transaction(conn, task_id, change) if conn is not None
                else self.store.update_task(task_id, change))
        parent = task.notification_policy.recipient_session_id or str(task.provenance.get('session_id') or '')
        if parent:
            if conn is None:
                self.gateway.event_bus.publish(parent, 'task.updated', {'task': task.to_dict()})
            else:
                event = self.gateway.store._insert_event(conn, parent, 'task.updated', {'task': task.to_dict()})
                self.gateway.store._queue_event(event)
        return task

    def open_turn(self, *, session_id: str, request_id: str, text: str, strategy: str,
                  owner: str, workspace: str = '', execution: dict | None = None,
                  agent_id: str = '') -> DurableTask:
        """One operational turn becomes one Goal/TaskCard. Replaying the request replays the card."""
        goal = Goal.from_owner(owner=owner or 'owner', objective=text.strip(), session_id=session_id)
        goal.goal_id = f'goal:{request_id}'  # derived, so replaying a request replays its card
        card = TaskCard.open(goal, strategy=strategy, request_id=request_id, task_id=f'turn:{request_id}')
        row = self.gateway.store.get_request(request_id) or {}
        # Only new, canonical, fully specified admissions can acquire a resume owner.
        resume = (execution is not None and execution == row.get('execution')
                  and bool(execution.get('workspace'))
                  and not (execution.get('options') or {}).get('task_id')
                  and not (execution.get('options') or {}).get('background')
                  and not execution.get('is_subordinate')
                  and (execution.get('options') or {}).get('source') in (None, '', 'user', 'client'))
        return self.admit_turn_card(card.to_payload(),
            execution=execution if resume else {'workspace': workspace}, resume=resume, agent_id=agent_id)

    def close_turn(self, task_id: str, result: dict, *, status: str, identity=None,
                   models: tuple[str, ...] = (), conn=None,
                   returned_cancelled: bool = False) -> tuple[DurableTask, Receipt]:
        """Verify what the worker returned and settle the card. Workers never choose the state.

        ``status`` is the request's terminal status. Only evidence the owner can
        check (a declared artifact, or a work-ledger receipt for a file that exists
        and matches) reaches ``completed_verified``.
        """
        task = (self.store.get_task_in_transaction(conn, task_id) if conn is not None
                else self.store.get_task(task_id))
        if task is None:
            raise ValueError(f'Unknown turn card: {task_id}')
        if not task.is_terminal:
            halt = str(result.get('halt_reason') or '')
            evidence: Any = None
            error: str | None = None
            if status == 'cancelled':
                state, error = TaskState.CANCELLED, str(result.get('error') or 'cancelled')
            elif status == 'execution_unknown':
                state, error = TaskState.PAUSED, 'Execution outcome unknown; reconcile effects before retry'
            elif status != 'completed':
                state, error = TaskState.FAILED, str(result.get('error') or status or 'failed')
            elif halt in {'needs_owner', 'blocked'}:
                state = TaskState.NEEDS_OWNER if halt == 'needs_owner' else TaskState.BLOCKED
                evidence = result.get('evidence') or result.get('output') or result
                error = str(result.get('error') or halt)
            elif result.get('error'):
                state, error = TaskState.FAILED, str(result['error'])
            elif halt == 'yielded' and task.payload.get('foreground_resume_version') == 1:
                if task.payload['execution'].get('attachments') or task.payload['execution'].get('attachment_ids'):
                    state, error = TaskState.FAILED, 'Foreground continuation cannot preserve pinned attachments; inspect retained work'
                else:
                    state, error = TaskState.PAUSED, 'Await the completed foreground receipt before continuation'
            elif halt:
                # A fresh artifact can be a partial checkpoint, not completion.
                # Only a clean worker outcome authorizes verification.
                state, error = TaskState.FAILED, halt
            else:
                verified, evidence = self.verify(task, result)
                if verified:
                    state, error = TaskState.COMPLETED_VERIFIED, None
                elif evidence == UNVERIFIABLE and not _asserts_success(result):
                    # Nothing the owner can check (an answer, not an artifact). That is
                    # the owner's call, not a failure and never a verified completion.
                    # A worker that asserted success it cannot show still fails.
                    state, error = TaskState.NEEDS_OWNER, UNVERIFIABLE
                    evidence = {'unverified_answer': str(result.get('text') or '')[:2000]}
                else:
                    state, error = TaskState.FAILED, str(evidence)
            task = self.settle_turn_card(task_id, state, evidence=evidence, error=error,
                                         result=result.get('output') or result.get('text') or result, conn=conn,
                                         returned_cancelled=returned_cancelled)
        card = task.payload.get('turn_card') or {}
        receipt = Receipt(
            receipt_id=f'rcpt_{str(card.get("request_id") or task_id)[:12]}',
            task_id=task.task_id,
            session_id=str(card.get('session_id') or ''),
            goal=task.goal,
            state=task.state.value,
            verification='verified' if task.state == TaskState.COMPLETED_VERIFIED else 'unverified',
            evidence=task.payload.get('verification'),
            strategy=str(card.get('strategy') or ''),
            models=tuple(m for m in models if m),
            entity_id=str(getattr(identity, 'entity_id', '') or ''),
            identity_name=str(getattr(identity, 'display_name', '') or ''),
        )
        return task, receipt

    def open_dispatch(self, *, orchestration_id: str, goal: str, worker: str, workspace: str = '',
                      artifacts: list[str] | None = None, session_id: str = '') -> DurableTask:
        """A task handed to an external-agent worker is still this owner's task.

        The orchestration service tracks the dispatch (transport); the worker's own
        ``completed`` is a worker status. This card is what settles, from evidence the
        owner can check: the artifacts declared here.
        """
        parent = session_id
        if not parent or not self.gateway.store.get_session(parent):
            parent = 'orchestration'
            self.gateway.store.ensure_session(parent, title='Worker dispatch', profile='jaeger')
        paths = self.artifact_paths(workspace, artifacts)
        goal_obj = Goal.from_owner(owner='owner', objective=goal.strip(), session_id=parent)
        goal_obj.goal_id = f'goal:orch:{orchestration_id}'
        card = TaskCard.open(goal_obj, strategy='specialist_delegation', request_id=f'orch:{orchestration_id}',
                             task_id=f'orch:{orchestration_id}', allowed=(worker,))
        return self.admit_turn_card(card.to_payload(), execution={'workspace': workspace},
                                    artifacts=paths, source='worker_dispatch')

    def close_dispatch(self, task_id: str, record: dict | None, *, cancelled: bool = False,
                       identity=None) -> tuple[DurableTask, Receipt]:
        """Settle a dispatch card from the orchestration record of what the worker returned."""
        res = (record or {}).get('result') or {}
        state = str(res.get('state') or (record or {}).get('state') or '')
        evidence = res.get('evidence') if isinstance(res.get('evidence'), dict) else {}
        worker = str((record or {}).get('worker') or '')
        output = str(res.get('output') or '')
        if cancelled or evidence.get('cancelled'):
            status, result = 'cancelled', {'error': 'cancelled'}
        elif state == 'unknown' or evidence.get('worker_cancel_confirmed') is False or evidence.get('surviving_pids'):
            status, result = 'execution_unknown', {'error': res.get('reason') or 'worker outcome unknown'}
        elif state in {'blocked', 'approval', 'auth', 'quota'}:
            halt = 'needs_owner' if state in {'approval', 'auth', 'quota'} else 'blocked'
            status, result = 'completed', {'halt_reason': halt, 'evidence': {'worker_state': state}, 'output': output}
        elif state == 'completed':
            # The worker's own "completed" is a claim, settled only by evidence.
            status, result = 'completed', {'output': output, 'worker_state': 'completed'}
        else:
            status, result = 'failed', {'error': res.get('reason') or output or state or 'worker failed'}
        return self.close_turn(task_id, result, status=status, identity=identity,
                               models=(worker,) if worker else ())

    def _reconcile_turn_card(self, task: DurableTask) -> None:
        """Settle a turn-owned card whose turn ended without settling it (crash, restart)."""
        rid = str(task.provenance.get('request_id') or '')
        if task.provenance.get('source') == 'worker_dispatch':
            orchestration = getattr(self.gateway, 'orchestration', None)
            oid = rid.removeprefix('orch:')
            if orchestration is None or oid in getattr(orchestration, '_active_executions', {}):
                return  # still dispatched: the orchestration service owns the worker
            record = orchestration.get_task(oid)
            if record is None and time.time() - task.updated_at < 30:
                return
            self.close_dispatch(task.task_id, record)
            return
        if not rid or rid in getattr(self.gateway, '_running_tasks', {}):
            return
        row = self.gateway.store.get_request(rid)
        status = (row or {}).get('status')
        if row is not None and status in {'admitted', 'running', 'cancelling'}:
            return  # the Gateway's own recovery owns an in-flight request
        if time.time() - task.updated_at < 30:
            return
        state = TaskState.CANCELLED if status == 'cancelled' else TaskState.FAILED
        self.settle_turn_card(task.task_id, state, error='The turn ended before this task was settled')

    def start(self):
        self._stopping = False
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self):
        self._stopping = True
        if self._loop_task:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        for task in self._active.values():
            task.cancel()
        await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._active.clear()

    async def _loop(self):
        while not self._stopping:
            try:
                await self.tick()
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Durable task dispatch failed; retrying from receipts')
            await asyncio.sleep(1)

    async def tick(self):
        # Yielding parents must not continuously reclaim every slot ahead of
        # their children. Least recently serviced work gets the next slice.
        for task in sorted(self.store.list_tasks(), key=lambda t: t.updated_at):
            # The turn that admitted this card is its executor and delivers its own
            # receipt; the scheduler must not start or re-deliver it.
            if task.provenance.get('turn_owned'):
                if task.payload.get('foreground_resume_version') == 1 and not task.is_terminal:
                    if task.cancellation:
                        await self.cancel(task.task_id)
                    else:
                        self._transfer_foreground(task)
                elif not task.is_terminal:
                    self._reconcile_turn_card(task)
                continue
            if task.is_terminal:
                try:
                    self._deliver(task)
                except ValueError:
                    # A deleted parent cannot consume the scheduler's whole tick.
                    # Keep the result available through /v1/tasks/{id}.
                    if task.task_id not in self._retained:
                        self._retained.add(task.task_id)
                        logging.getLogger(__name__).warning('Task %s result retained: parent session unavailable', task.task_id)
                continue
            if task.state == TaskState.PAUSED and task.provenance.get('authorized'):
                receipt = self.gateway.store.get_request(f'{task.task_id}:{task.payload.get("attempt", 0)}') or {}
                if (receipt.get('status') not in {'completed', 'failed', 'cancelled'}
                        and not (task.cancellation and not receipt)):
                    continue
            elif task.state not in (TaskState.QUEUED, TaskState.RUNNING):
                continue
            if not task.provenance.get('authorized') or task.task_id in self._active:
                continue
            if task.next_execution and task.next_execution > time.time():
                continue
            if len(self._active) >= 2:
                break
            operation = asyncio.create_task(self._execute(task.task_id))
            self._active[task.task_id] = operation
            operation.add_done_callback(lambda done, tid=task.task_id: self._finished(tid, done))

    def _transfer_foreground(self, task):
        """Adopt a finished slice, never restart the request that produced it.

        A crash before its canonical receipt is committed is owned by Gateway
        recovery. A crash after that commit can replay this idempotent transfer.
        """
        if task.cancellation or not task.provenance.get('authorized'):
            return
        rid = task.payload.get('original_request_id')
        if not rid or rid in getattr(self.gateway, '_running_tasks', {}):
            return
        row = self.gateway.store.get_request(rid) or {}
        if row.get('status') in {'admitted', 'running', 'cancelling'}:
            return
        result = row.get('result') or {}
        if row.get('status') in {'completed', 'failed', 'cancelled'} and (
                row['status'] != 'completed' or result.get('error') or result.get('halt_reason') != 'yielded'):
            self.close_turn(task.task_id, result, status=row['status'])
            return
        if not row:
            self._reconcile_turn_card(task)
            return
        def transfer(current):
            if (current.is_terminal or not current.provenance.get('turn_owned')
                    or current.payload.get('foreground_resume_version') != 1):
                return
            if current.cancellation or not current.provenance.get('authorized'):
                return
            cancellations = getattr(self.gateway, '_cancellations', None)
            if cancellations and cancellations.is_cancelled(rid):
                current.cancellation = 'Cancelled by user'
                authoritative_transition(current, TaskState.PAUSED, error='Cancellation requested; reconcile owned children')
                return
            if row.get('status') == 'execution_unknown':
                authoritative_transition(current, TaskState.PAUSED,
                    error='Execution outcome unknown; reconcile effects before retry')
                return
            if row.get('status') != 'completed' or result.get('error') or result.get('halt_reason') != 'yielded':
                # Recovery may have settled a different outcome after close_turn.
                if row.get('status') in {'cancelled', 'failed'}:
                    authoritative_transition(current, TaskState.CANCELLED if row['status'] == 'cancelled'
                                             else TaskState.FAILED, error=result.get('error') or row['status'])
                return
            execution = current.payload['execution']
            reason = None
            if execution != row.get('execution'):
                reason = 'Foreground execution authority changed; no automatic continuation'
            elif execution.get('attachments') or execution.get('attachment_ids'):
                reason = 'Foreground continuation cannot preserve pinned attachments; inspect retained work'
            elif execution.get('interaction_tier') not in {'agent', 'jaeger'}:
                reason = 'Foreground interaction tier is unresolved; no automatic continuation'
            elif not Path(str(execution.get('workspace') or '')).is_absolute():
                reason = 'Foreground workspace is unresolved; no automatic continuation'
            from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX, split_routed_model_id
            route_provider, route_model = split_routed_model_id(str(execution.get('model') or ''))
            provider = str(execution.get('provider') or route_provider or '').lower()
            if not reason and (not route_model or route_model.lower() in {'default', 'jaeger', 'local', 'none'}
                    or not provider or provider in {'local', 'cli'}):
                reason = 'Foreground model/provider route is unresolved; no automatic continuation'
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
            native = row.get('native_run_id')
            checkpoint = None
            if not reason:
                try:
                    runs = SqliteRunStore()
                    run = runs.get(native) if native else None
                    checkpoint = runs.latest_checkpoint(native) if run else None
                    if (not native or not str(row.get('native_session') or '').startswith(OWNER_RUN_SESSION_PREFIX)
                            or not run or run.state not in {'active', 'recoverable'}
                            or not checkpoint or not checkpoint.cursor.get('messages')):
                        reason = 'Foreground native checkpoint is unavailable; inspect retained work without replay'
                    elif EntityRuntime.run_has_indeterminate_effects(native):
                        authoritative_transition(current, TaskState.PAUSED,
                            error='Execution outcome unknown; reconcile effects before retry')
                        return
                except Exception:
                    reason = 'Foreground native checkpoint cannot be read; inspect retained work without replay'
            if reason:
                authoritative_transition(current, TaskState.FAILED, error=reason)
                return
            current.payload['native_run_id'] = native
            current.payload['attempt'] = 0
            current.result = result.get('output') or result
            if not any(run.run_id == rid for run in current.run_history):
                current.run_history.append(TaskRunRecord(run_id=rid, started_at=row['created_at']))
            current.provenance['turn_owned'] = False
            authoritative_transition(current, TaskState.QUEUED, error=None)
            self._checkpoint(current, row)
        changed = False
        def update(current):
            nonlocal changed
            before = json.dumps(current.to_dict(), sort_keys=True)
            transfer(current)
            changed = before != json.dumps(current.to_dict(), sort_keys=True)
        updated = self.store.update_task(task.task_id, update)
        if changed:
            self.gateway.event_bus.publish(updated.notification_policy.recipient_session_id,
                                           'task.updated', {'task': updated.to_dict()})

    def _finished(self, task_id, operation):
        self._active.pop(task_id, None)
        if not operation.cancelled() and operation.exception() is not None:
            logging.getLogger(__name__).error('Task %s will reconcile from its receipt: %s', task_id, operation.exception())

    def _execution_session(self, task, *, admitted=False):
        """Bind an unstarted child to its saved execution identity, never rebind.

        Existing admitted children without an identity need owner inspection;
        adding specialist metadata after admission would change execution truth.
        """
        sid = f'task:{task.task_id}'
        existing = self.gateway.store.get_session(sid)
        previous = (existing or {}).get('metadata') or {}
        metadata = {'task_id': task.task_id, 'parent_session_id': task.notification_policy.recipient_session_id,
                    'actionable': True}
        if previous.get('task_id') not in (None, task.task_id):
            raise ValueError('Task child belongs to a different saved task; no dispatch')
        if task.payload.get('foreground_resume_version') == 1 or task.payload.get('background_admission_version') == 1:
            if existing and (previous.get('task_id') != task.task_id
                    or str(existing.get('agent_id') or previous.get('agent_id') or '') != task.agent_id):
                raise ValueError('Foreground continuation session identity differs; no dispatch')
            metadata['route_checked'] = True
        if task.payload.get('background_admission_version') == 1:
            metadata['execution_mode'] = 'agent'
        if task.agent_id:
            bound = (existing or {}).get('agent_id') or previous.get('agent_id')
            if bound and bound != task.agent_id:
                raise ValueError('Task child execution identity differs from saved task; no rebind or dispatch')
            if admitted and not bound:
                raise ValueError('Admitted task child has no saved execution identity; inspect its receipt without replay')
            metadata.update(agent_id=task.agent_id, agent_pinned=True, route_checked=True)
        return self.gateway.store.ensure_session(sid, title=task.goal[:100], profile='jaeger',
            workspace=str(task.payload['execution'].get('workspace') or ''), metadata=metadata)

    def handoff_workspace(self, context):
        """An inherited default is not a user-selected specialist project."""
        from jaeger_ai.core.runtime.execution_defaults import inherit_instance_defaults, InstanceDefaultsConflict
        execution = context.get('execution') or {}
        source = self.gateway.store.get_request(context.get('request_id'))
        marker = inherit_instance_defaults(source, execution,
            session_id=context.get('session_id'), claimed=execution.get('_instance_defaults'))
        if marker.get('workspace') != execution.get('workspace'):
            raise InstanceDefaultsConflict('Cannot prove inherited instance workspace; no handoff')
        return ''  # Preserve the specialist's prior instance-default behavior.

    @staticmethod
    def _instance_defaults_source(task):
        if task.payload.get('background_admission_version') == 1:
            return None  # Its canonical source is this task, not a foreground request.
        marker = (task.payload.get('execution') or {}).get('_instance_defaults')
        if marker is None:
            return None
        return {'request_id': task.payload.get('original_request_id') or task.provenance.get('request_id'),
                'session_id': task.provenance.get('session_id'), 'claimed': marker}

    def _validate_instance_defaults(self, task, execution, conn=None):
        from .background_admission import validate
        validate(self, task, conn)
        from jaeger_ai.core.runtime.execution_defaults import inherit_instance_defaults
        origin = self._instance_defaults_source(task)
        if origin is None:
            return
        parent = task.notification_policy.recipient_session_id
        if parent and origin['session_id'] != parent:
            from jaeger_ai.core.runtime.execution_defaults import InstanceDefaultsConflict
            raise InstanceDefaultsConflict('Instance defaults source differs from task originating session; no dispatch')
        if conn is None:
            source = self.gateway.store.get_request(origin['request_id'])
        else:
            row = conn.execute('SELECT * FROM client_requests WHERE request_id=? AND session_id=?',
                (origin['request_id'], origin['session_id'])).fetchone()
            source = self.gateway.store._request_row(row) if row else None
        marker = inherit_instance_defaults(source, execution,
            session_id=origin['session_id'], claimed=origin['claimed'], authority=task.payload['execution'])
        if execution.get('_instance_defaults') != marker:
            from jaeger_ai.core.runtime.execution_defaults import InstanceDefaultsConflict
            raise InstanceDefaultsConflict('Inherited instance mode differs from canonical source; no dispatch')

    def _admission_guard(self, conn, task, *, execution=None, prompt=None):
        """Revalidate revocation/cancellation in the canonical request commit."""
        row = conn.execute('SELECT task_json FROM durable_tasks WHERE task_id=?', (task.task_id,)).fetchone()
        current = DurableTask.from_dict(json.loads(row[0])) if row else None
        if current is None or current.is_terminal or current.cancellation or not current.provenance.get('authorized'):
            raise TaskAdmissionChanged('Task authorization or cancellation changed before admission; no dispatch')
        if current.payload.get('background_admission_version') == 1:
            from .background_admission import validate, authority
            try:
                validate(self, current, conn)
                if authority(current) != authority(task):
                    raise ValueError('Background task authority changed before admission')
            except ValueError as exc:
                raise TaskAdmissionChanged(str(exc)) from exc
        if self._instance_defaults_source(task) is not None:
            if (current.payload.get('execution') != task.payload.get('execution')
                    or self._instance_defaults_source(current) != self._instance_defaults_source(task)):
                raise TaskAdmissionChanged('Task instance scope changed before admission; no dispatch')
            self._validate_instance_defaults(current, execution or current.payload['execution'], conn)
        if current.payload.get('foreground_resume_version') == 1 and current.payload.get('execution') != task.payload.get('execution'):
            raise TaskAdmissionChanged('Task execution authority changed before admission; no dispatch')
        if int(current.payload.get('attempt', 0)) != int(task.payload.get('attempt', 0)):
            raise TaskAdmissionChanged('Task attempt changed before admission; no dispatch')
        if current.payload.get('foreground_resume_version') == 1:
            original = conn.execute('SELECT * FROM client_requests WHERE request_id=?',
                                   (current.payload['original_request_id'],)).fetchone()
            if (not original or original['status'] != 'completed'
                    or json.loads(original['execution_json']) != current.payload['execution']
                    or self.gateway._cancellations.is_cancelled(current.payload['original_request_id'])):
                raise TaskAdmissionChanged('Original foreground authority or cancellation changed; no dispatch')
            from jaeger_ai.core.gateway.owner_receipts import check_agent_identity
            check_agent_identity(conn, original)
            if execution is not None:
                # Commit the per-attempt contract with request admission. Owner
                # feedback may change later; the admitted inputs never do.
                expected = json.loads(json.dumps(execution))
                expected.pop('attachment_ids', None)
                current.payload.setdefault('continuation_admissions', {})[
                    f'{current.task_id}:{current.payload.get("attempt", 0)}'] = {
                        'execution': expected, 'input_text': prompt}
                conn.execute('UPDATE durable_tasks SET task_json=? WHERE task_id=?',
                             (json.dumps(current.to_dict()), current.task_id))
        if not current.provenance.get('webhook_subscription_id'):
            return
        from jaeger_ai.features.webhooks.owner import execution_allowed
        if self.gateway._current_tier() == 'chat' or not execution_allowed(self.gateway, current, connection=conn):
            raise ValueError('Webhook subscription revoked or changed before admission; no dispatch')

    def background_dispatch_guard(self, conn, row):
        """Find authority by canonical request/session, not caller task options."""
        sid = row.get('session_id') or ''
        if not sid.startswith('task:'):
            return None
        task = self.store.get_task_in_transaction(conn, sid[5:])
        if task is None or task.payload.get('background_admission_version') != 1:
            return None
        from jaeger_ai.core.gateway.owner_receipts import _lease
        lease = self.gateway._owner_receipt_lease
        _lease(conn, lease['owner_pid'], lease['started_at'])
        self._admission_guard(conn, task)
        if (row.get('request_id') != f'{task.task_id}:{task.payload.get("attempt", 0)}'
                or self.gateway._cancellations.is_cancelled(row['request_id'])
                or self._continuation_receipt_error(task, row)):
            raise TaskAdmissionChanged('Background dispatch differs from current task admission')
        return task

    def background_binding_guard(self, conn, row, native, native_session):
        task = self.background_dispatch_guard(conn, row)
        if task is None:
            return
        from .background_receipts import assert_open
        assert_open(conn, row)
        if (native_session != 'owner:task:'+task.task_id or not native
                or row.get('status') not in {'admitted', 'running', 'awaiting_approval'}):
            raise TaskAdmissionChanged('Background native binding is not an active owner run')
        contract = task.payload['background_admissions'][row['request_id']]
        from jaeger_ai.core.entity.runtime import EntityRuntime
        from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
        import os
        run = SqliteRunStore().get(native)
        if run is None:
            raise TaskAdmissionChanged('Background native run is unavailable')
        previous = contract.get('native_run_id')
        if previous and previous != native:
            prior = SqliteRunStore().get(previous)
            if (prior is None or prior.state not in {'completed', 'failed', 'cancelled'}
                    or EntityRuntime.run_has_indeterminate_effects(previous)):
                raise TaskAdmissionChanged('Background previous native run is unsettled')
        sources = conn.execute('''SELECT DISTINCT r.* FROM client_requests r
            WHERE r.request_id<>? AND (r.native_run_id=? OR r.request_id IN (
                SELECT admissions.key FROM durable_tasks t,
                json_each(t.task_json, '$.payload.background_admissions') admissions,
                json_each(admissions.value, '$.native_run_ids') runs WHERE runs.value=?))''',
            (row['request_id'], native, native)).fetchall()
        if not sources and run.state not in {'active', 'running', 'verifying'}:
            raise TaskAdmissionChanged('Background native lifecycle does not authorize fresh binding')
        from jaeger_ai.core.gateway.session_store import pid_is_alive
        if ((not sources and run.owner_pid != os.getpid())
                or (sources and run.owner_pid not in {None, os.getpid()} and pid_is_alive(run.owner_pid))):
            raise TaskAdmissionChanged('Background native run has no qualified producer ownership')
        for source in sources:
            source = self.gateway.store._request_row(source)
            admission = task.payload['background_admissions'].get(source['request_id'])
            operation = self.gateway._running_tasks.get(source['request_id'])
            # Durable yielded natives intentionally remain active. Only this
            # lease's returned producer may transfer that active trajectory;
            # absence of an operation after restart is not returned proof.
            live_returned = (run.owner_pid == os.getpid()
                and admission is not None
                and admission.get('lease') == self.gateway._owner_receipt_lease
                and (operation is None or operation.done()))
            lifecycle_known = run.state in {'completed', 'failed', 'cancelled'} or (
                run.state in {'active', 'running', 'verifying'} and live_returned)
            if (not lifecycle_known or (operation is not None and not operation.done())
                    or not admission or admission['attempt'] >= contract['attempt']
                    or source['status'] not in {'completed', 'failed'}
                    or self._continuation_receipt_error(task, source)
                    or any(EntityRuntime.run_has_indeterminate_effects(run_id)
                           for run_id in admission.get('native_run_ids', [native]))
                    or self._background_children_unsettled(source)):
                raise TaskAdmissionChanged('Background native run belongs to another or unsettled attempt')
        contract.setdefault('native_run_ids', [])
        if native not in contract['native_run_ids']:
            contract['native_run_ids'].append(native)
        contract.update(native_run_id=native, native_session=native_session)
        conn.execute('UPDATE durable_tasks SET task_json=? WHERE task_id=?',
                     (json.dumps(task.to_dict()), task.task_id))
        return {(task.task_id, row['request_id']),
                *((task.task_id, source['request_id']) for source in sources)}

    def _background_children_unsettled(self, source):
        from jaeger_ai.core.gateway.handoff_ownership import owned_children
        from jaeger_ai.core.gateway.handoff_cancellation import status, unconfirmed_ids
        return bool(unconfirmed_ids([status(self.gateway, child)
                    for child in owned_children(self.gateway, source)]))

    def _background_admission_guard(self, conn, task, resolved, prompt):
        """Bind the exact final request snapshot atomically, never caller options."""
        from .background_admission import clone, authority
        self._admission_guard(conn, task)
        from jaeger_ai.core.gateway.owner_receipts import _lease
        lease = self.gateway._owner_receipt_lease
        _lease(conn, lease['owner_pid'], lease['started_at'])
        expected = self._continuation_execution(task)
        expected.pop('attachment_ids', None)
        marker = expected.pop('_instance_defaults', None)
        if resolved != expected or prompt != self._continuation_prompt(task):
            raise TaskAdmissionChanged('Resolved background request differs from saved task scope')
        if marker:
            resolved['_instance_defaults'] = marker
        current = self.store.get_task_in_transaction(conn, task.task_id)
        rid = f'{task.task_id}:{task.payload.get("attempt", 0)}'
        proof = {'task_id': task.task_id, 'attempt': task.payload.get('attempt', 0),
            'request_id': rid, 'session_id': 'task:'+task.task_id, 'lease': clone(lease),
            'execution': clone(resolved), 'input_text': prompt,
            'authority': authority(task), 'objective_version': task.payload['background_objective_version'],
            'research_contract': clone(task.payload.get('research_contract')),
            'research_artifacts': clone(task.payload.get('research_artifacts'))}
        current.payload.setdefault('background_admissions', {})[rid] = proof
        conn.execute('UPDATE durable_tasks SET task_json=? WHERE task_id=?',
                     (json.dumps(current.to_dict()), current.task_id))

    @staticmethod
    def _continuation_execution(task):
        execution = json.loads(json.dumps(task.payload['execution']))
        # Foreground journal identity stays on the canonical source request.
        # Its existing admission guard validates that source; a durable child
        # never claims fresh foreground receipt eligibility.
        execution.pop('_owner_agent', None)
        execution['is_subordinate'] = True
        execution['options'] = {**(execution.get('options') or {}), 'background': True,
                                'source': 'durable_task', 'task_id': task.task_id,
                                'verification_error': task.error}
        if task.payload.get('foreground_resume_version') == 1 or task.payload.get('background_admission_version') == 1:
            execution['attachment_ids'] = []  # never inherit new child-session inputs
        return execution

    @staticmethod
    def _continuation_prompt(task):
        prompt = ('Execute this authorized durable task fully. Do not queue the same work again. '
                  'Use the real tools, preserve progress, verify the requested outcome, and return the result. '
                  + EVIDENCE_CONTRACT + '\n\n'
                  + task.goal)
        if task.payload.get('artifacts'):
            prompt += '\nRequired result artifacts: ' + json.dumps(task.payload['artifacts'])
        if 'research_contract' in task.payload:
            from .research import guidance
            prompt += '\n' + guidance(task.payload['research_contract'])
            prompt += '\nResearch artifact paths: ' + json.dumps(task.payload['research_artifacts'], sort_keys=True)
            prompt += '\nUse these owner-designated task-specific paths instead of the contract basenames.'
        if task.error:
            prompt += '\nOwner verification requires correction: ' + str(task.error)
        if task.result:
            prompt += '\nPrevious checkpoint (retained work, not necessarily verified):\n' + str(task.result)
        return prompt

    def native_reuse_guard(self, task_id: str, run_id: str, native_session: str):
        """Reuse only through the existing canonical foreground transfer proof.

        The callable runs inside the native-binding transaction. Client options
        or a raw task ID alone are never a native ownership grant.
        """
        def validate(conn, raw_row):
            from jaeger_ai.core.gateway.owner_receipts import _lease, OwnerReceiptConflict
            lease = getattr(self.gateway, '_owner_receipt_lease', None)
            if not lease:
                raise OwnerReceiptConflict('Native transfer has no current Gateway lease')
            _lease(conn, lease['owner_pid'], lease['started_at'])
            task = self.store.get_task_in_transaction(conn, task_id)
            if task is None or task.payload.get('foreground_resume_version') != 1:
                return set()
            row = self.gateway.store._request_row(raw_row)
            self._admission_guard(conn, task)
            from jaeger_ai.core.gateway.owner_receipts import OWNER_RUN_SESSION_PREFIX
            if (row['status'] not in {'admitted', 'running', 'awaiting_approval'}
                    or self.gateway._cancellations.is_cancelled(row['request_id'])
                    or task.provenance.get('turn_owned') or row['request_id'] != f'{task_id}:{task.payload.get("attempt", 0)}'
                    or run_id != task.payload.get('native_run_id')
                    or native_session != OWNER_RUN_SESSION_PREFIX + f'task:{task_id}'
                    or self._continuation_receipt_error(task, row)):
                raise OwnerReceiptConflict('Native reuse differs from canonical foreground transfer')
            return {task.payload['original_request_id']}
        return validate

    def _continuation_receipt_error(self, task, row):
        """An ID collision is not this task's receipt, even when it is terminal."""
        if not row:
            return None
        sid = f'task:{task.task_id}'
        if row.get('session_id') != sid:
            return 'Continuation receipt belongs to another session; inspect without replay'
        if task.payload.get('background_admission_version') == 1:
            from .background_admission import receipt_error
            return receipt_error(task, row)
        if task.payload.get('foreground_resume_version') != 1:
            return None  # Legacy tasks do not have a full frozen authority contract.
        rid = row.get('request_id')
        contract = task.payload.get('continuation_admissions', {}).get(rid)
        if contract is None:
            # Only an unstarted, otherwise exact admission can recover the tiny
            # admission-before-binding window. A running/terminal row proves no
            # such ownership and must not be adopted from its ID alone.
            if (row.get('status') != 'admitted' or row.get('native_run_id')
                    or rid != f'{task.task_id}:{task.payload.get("attempt", 0)}'):
                return 'Continuation receipt has no retained admission contract; inspect without replay'
            expected = self._continuation_execution(task)
            expected.pop('attachment_ids', None)
            contract = {'execution': expected, 'input_text': self._continuation_prompt(task)}
        if row.get('execution') != contract['execution'] or row.get('input_text') != contract['input_text']:
            return 'Continuation receipt differs from retained execution authority; inspect without replay'
        native = row.get('native_run_id')
        native_session = row.get('native_session')
        if row.get('status') == 'admitted' and not native and not native_session:
            return None
        from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX
        if native != task.payload.get('native_run_id') or native_session != OWNER_RUN_SESSION_PREFIX + sid:
            return 'Continuation receipt differs from retained native ownership; inspect without replay'
        return None

    @staticmethod
    def _visible_task(task):
        """Compare outcome/progress, not the timestamp of another observation."""
        value = task.to_dict()
        value.pop('updated_at', None)
        value = json.loads(json.dumps(value))
        value.get('payload', {}).get('last_progress', {}).pop('observed_at', None)
        return value

    def _retain_foreign_receipt(self, task_id, reason, *, cancelled=False):
        before = self._visible_task(self.store.get_task(task_id))
        def hold(current):
            if not current.is_terminal:
                authoritative_transition(current, TaskState.PAUSED, error=reason)
                if cancelled:
                    current.cancellation = 'Cancelled by user'
        retained = self.store.update_task(task_id, hold)
        if self._visible_task(retained) != before:
            self.gateway.event_bus.publish(retained.notification_policy.recipient_session_id,
                'task.updated', {'task': retained.to_dict()})

    async def _execute(self, task_id):
        task = self.store.get_task(task_id)
        if task is None or task.is_terminal:
            return
        before = self._visible_task(task)
        sid = f'task:{task_id}'
        attempt = int(task.payload.get('attempt', 0))
        rid = f'{task_id}:{attempt}'
        row = self.gateway.store.get_request(rid)
        reason = self._continuation_receipt_error(task, row)
        if reason:
            self._retain_foreign_receipt(task_id, reason)
            return
        if task.cancellation and row is None:
            # This is reconciliation, not dispatch. A disabled specialist or
            # revoked subscription must not strand cancellation of old children.
            await self.cancel(task_id)
            return
        if task.payload.get('foreground_resume_version') == 1:
            original = self.gateway.store.get_request(task.payload['original_request_id']) or {}
            if self.gateway._cancellations.is_cancelled(task.payload['original_request_id']):
                await self.cancel(task_id)
                return
            if (not task.provenance.get('authorized') or task.provenance.get('turn_owned')
                    or original.get('status') != 'completed'
                    or original.get('execution') != task.payload['execution']):
                return
        if (task.payload.get('foreground_resume_version') == 1
                and (row is None or row.get('status') in {'admitted', 'running'})
                and rid not in self.gateway._running_tasks):
            from jaeger_ai.core.entity.runtime import EntityRuntime
            reason = None
            if EntityRuntime.run_has_indeterminate_effects(task.payload['native_run_id']):
                reason = 'Execution outcome unknown; reconcile effects before retry'
            if reason:
                def hold_unknown(current):
                    if not current.is_terminal and not current.cancellation:
                        authoritative_transition(current, TaskState.PAUSED, error=reason)
                self.store.update_task(task_id, hold_unknown)
                return
        execution = self._continuation_execution(task)
        try:
            self._validate_instance_defaults(task, execution)
            if row is not None and self._instance_defaults_source(task) is not None:
                self._validate_instance_defaults(task, row.get('execution') or {})
        except ValueError as exc:
            self._retain_foreign_receipt(task_id, str(exc))
            return
        if row is None or row.get('status') in {'admitted', 'running'} and rid not in self.gateway._running_tasks:
            try:
                if task.provenance.get('webhook_subscription_id'):
                    from jaeger_ai.features.webhooks.owner import execution_allowed
                    if not execution_allowed(self.gateway, task):
                        raise ValueError('Webhook subscription revoked or changed; inspect proposal before dispatch')
                self._execution_session(task, admitted=row is not None)
                if task.agent_id:
                    # Current registry execution protections still apply after a
                    # delayed approval. No fallback to the lead on disappearance.
                    registry = getattr(self.gateway, '_registry', None)
                    if registry is not None:
                        agent = registry().get_agent(task.agent_id)
                        if agent is None or agent.disabled:
                            raise ValueError('Saved task agent is unavailable or disabled; no dispatch')
            except ValueError as exc:
                reason = str(exc)
                def hold(current):
                    if not current.is_terminal:
                        authoritative_transition(current, TaskState.PAUSED, error=reason)
                retained = self.store.update_task(task_id, hold)
                self.gateway.event_bus.publish(task.notification_policy.recipient_session_id or sid,
                    'task.updated', {'task': retained.to_dict()})
                return
        prompt = self._continuation_prompt(task)
        row = self.gateway.store.get_request(rid)
        reason = self._continuation_receipt_error(task, row)
        if reason:
            self._retain_foreign_receipt(task_id, reason)
            return
        if row is None:
            try:
                admitted = self.gateway.store.admit_request(sid, prompt, request_id=rid, requested=execution,
                    admission_guard=lambda conn: self._admission_guard(conn, task, execution=execution, prompt=prompt),
                    instance_defaults_source=self._instance_defaults_source(task),
                    admission_snapshot_guard=(lambda conn, resolved: self._background_admission_guard(conn, task, resolved, prompt))
                        if task.payload.get('background_admission_version') == 1 else None)
            except ValueError as exc:
                if isinstance(exc, TaskAdmissionChanged):
                    # The current durable row owns the decision. In particular,
                    # never overwrite a cancellation or a newer attempt with
                    # this executor's stale snapshot.
                    return
                if isinstance(exc, RequestConflict):
                    # Another admission can claim this global id after the
                    # precheck. Keep the task for reconciliation; never adopt,
                    # bind, dispatch or cancel the colliding receipt.
                    current = self.store.get_task(task_id)
                    if current is None or f'{task_id}:{current.payload.get("attempt", 0)}' != rid:
                        return
                    reason = self._continuation_receipt_error(
                        current, self.gateway.store.get_request(rid))
                    self._retain_foreign_receipt(task_id, reason or
                        'Continuation request identity conflict; inspect without replay')
                    return
                from jaeger_ai.core.runtime.execution_defaults import InstanceDefaultsConflict
                if not task.provenance.get('webhook_subscription_id') and not isinstance(exc, InstanceDefaultsConflict):
                    raise
                reason = str(exc)
                def hold_admission(current):
                    if not current.is_terminal:
                        authoritative_transition(current, TaskState.PAUSED, error=reason)
                held = self.store.update_task(task_id, hold_admission)
                self.gateway.event_bus.publish(task.notification_policy.recipient_session_id or sid,
                    'task.updated', {'task': held.to_dict()})
                return
            task = self.store.get_task(task_id)
            reason = self._continuation_receipt_error(task, admitted)
            if reason:
                self._retain_foreign_receipt(task_id, reason)
                return
            if task.payload.get('native_run_id'):
                from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX
                try:
                    self.gateway.store.bind_native(rid, native_run_id=task.payload['native_run_id'], native_session=f'{OWNER_RUN_SESSION_PREFIX}{sid}',
                        native_reuse_guard=self.native_reuse_guard(task_id, task.payload['native_run_id'], f'{OWNER_RUN_SESSION_PREFIX}{sid}'),
                        native_binding_guard=self.background_binding_guard)
                except TaskAdmissionChanged as exc:
                    self._retain_foreign_receipt(task_id, str(exc))
                    return
            self.gateway._start_admitted_turn(admitted, sid, prompt)
        elif row.get('status') in {'admitted', 'running'} and rid not in self.gateway._running_tasks:
            if task.payload.get('foreground_resume_version') == 1:
                # Reconcile admission-before-binding crashes against the current
                # task grant, never against this executor's stale snapshot.
                with self.gateway.store._immediate() as conn:
                    try:
                        self._admission_guard(conn, task, execution=row['execution'], prompt=row['input_text'])
                    except TaskAdmissionChanged:
                        return
                # Preserve the original run even if the process died immediately
                # after request admission and before binding it.
                if not row.get('native_run_id'):
                    from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX
                    row = self.gateway.store.bind_native(rid,
                        native_run_id=task.payload['native_run_id'],
                        native_session=f'{OWNER_RUN_SESSION_PREFIX}{sid}',
                        native_reuse_guard=self.native_reuse_guard(task_id, task.payload['native_run_id'], f'{OWNER_RUN_SESSION_PREFIX}{sid}'))
            # A persisted admission without dispatch is safe. Unknown effects are
            # recovered separately by the Gateway; never create a fresh run here.
            self.gateway._start_admitted_turn({**row, 'accepted': True}, sid, prompt)
        def started(current):
            if current.is_terminal or int(current.payload.get('attempt', 0)) != attempt:
                return
            if current.state == TaskState.QUEUED:
                authoritative_transition(current, TaskState.RUNNING)
            receipt = self.gateway.store.get_request(rid) or {}
            reason = self._continuation_receipt_error(current, receipt)
            if reason:
                authoritative_transition(current, TaskState.PAUSED, error=reason)
                return
            if not any(run.run_id == rid for run in current.run_history):
                current.run_history.append(TaskRunRecord(
                    run_id=rid, started_at=receipt.get('created_at') or time.time()))
            self._checkpoint(current, receipt)
        self.store.update_task(task_id, started)
        operation = self.gateway._running_tasks.get(rid)
        if operation is not None:
            await asyncio.shield(operation)
        row = self.gateway.store.get_request(rid) or {}
        current = self.store.get_task(task_id)
        reason = self._continuation_receipt_error(current, row)
        if reason:
            self._retain_foreign_receipt(task_id, reason)
            return
        status = row.get('status')
        result = row.get('result') or {}
        if status in {'admitted', 'running'}:
            return
        # A fresh file may only be a checkpoint. A completed request means the
        # slice ended, not that a yielded/blocked/failed objective is complete.
        # The runtime contract emits no halt marker on a clean finish; any
        # explicit backstop (including future markers) must not verify a file.
        can_verify = (status == 'completed' and not result.get('error')
                      and result.get('halt_reason') in (None, ''))
        verified, evidence = self.verify(task, result) if can_verify else (False, '')
        current = self.store.get_task(task_id)
        children = await self._cancel_owned_children(current, row) if current and current.cancellation else []
        from jaeger_ai.core.gateway.handoff_cancellation import unconfirmed_ids
        unconfirmed = unconfirmed_ids(children)
        def settle(current):
            # More than one waiter can reconcile the same request receipt.
            # Compare under the store's write transaction, not before the await.
            if current.is_terminal or int(current.payload.get('attempt', 0)) != attempt:
                return
            if current.payload.get('background_admission_version') == 1:
                reason = self._continuation_receipt_error(current, row)
                if reason or not current.provenance.get('authorized'):
                    authoritative_transition(current, TaskState.PAUSED,
                        error=reason or 'Background authorization revoked before verification')
                    return
            current.result = result.get('output') or result
            if row.get('native_run_id'):
                current.payload['native_run_id'] = row['native_run_id']
            current.payload['verification'] = evidence
            native_unknown = False
            if current.payload.get('foreground_resume_version') == 1:
                from jaeger_ai.core.entity.runtime import EntityRuntime
                native = row.get('native_run_id') or current.payload.get('native_run_id')
                native_unknown = bool(native) and EntityRuntime.run_has_indeterminate_effects(native)
            if native_unknown:
                current.payload['cancellation_children'] = children
                authoritative_transition(current, TaskState.PAUSED,
                    error='Execution outcome unknown; reconcile effects before retry or cancellation')
            elif current.cancellation and unconfirmed:
                current.payload['cancellation_children'] = children
                authoritative_transition(current, TaskState.PAUSED,
                    error='Cancellation requested; owned child execution remains unconfirmed')
            elif current.cancellation and status != 'execution_unknown':
                current.payload['cancellation_children'] = children
                authoritative_transition(current, TaskState.CANCELLED)
            elif verified:
                try:
                    authoritative_transition(
                        current, TaskState.COMPLETED_VERIFIED, evidence=evidence,
                    )
                except CompletionError as exc:
                    authoritative_transition(current, TaskState.FAILED, error=str(exc))
            elif can_verify and 'research_contract' in current.payload:
                authoritative_transition(current, TaskState.NEEDS_OWNER,
                    evidence={'retained_partial_result': current.result}, error=str(evidence))
            elif status == 'cancelled':
                authoritative_transition(current, TaskState.CANCELLED)
            elif status == 'execution_unknown':
                authoritative_transition(
                    current, TaskState.PAUSED,
                    error='Execution outcome unknown; reconcile effects before retry',
                )
            elif result.get('halt_reason') == 'yielded':
                current.payload['attempt'] = attempt + 1
                authoritative_transition(current, TaskState.QUEUED)
                current.next_execution = time.time() + 1
            elif str(result.get('halt_reason') or '') in {'needs_owner', 'blocked'}:
                target = (TaskState.NEEDS_OWNER if result.get('halt_reason') == 'needs_owner'
                          else TaskState.BLOCKED)
                try:
                    authoritative_transition(
                        current, target,
                        evidence=result.get('evidence') or result.get('output') or result,
                        error=str(result.get('error') or target.value),
                    )
                except CompletionError as exc:
                    authoritative_transition(current, TaskState.FAILED, error=str(exc))
            elif result.get('halt_reason'):
                # Only the explicit yielded contract schedules another slice.
                # Resetting a loop breaker's counters can repeat failed effects;
                # retain the halt for review instead of consuming a retry.
                authoritative_transition(current, TaskState.FAILED,
                    error=str(result.get('error') or result['halt_reason']))
            elif current.retry_policy.can_retry():
                current.retry_policy.current_retries += 1
                current.payload['attempt'] = attempt + 1
                authoritative_transition(
                    current, TaskState.QUEUED,
                    error=str(result.get('error') or evidence or 'Outcome not verified'),
                )
                current.next_execution = time.time() + current.retry_policy.backoff_seconds
            else:
                authoritative_transition(
                    current, TaskState.FAILED,
                    error=str(result.get('error') or evidence or 'Outcome not verified after retries'),
                )
            self._checkpoint(current, row)
        task = self.store.update_task(task_id, settle)
        if self._visible_task(task) != before:
            self.gateway.event_bus.publish(task.notification_policy.recipient_session_id or sid,
                                           'task.updated', {'task': task.to_dict()})
        if task.is_terminal:
            self._settle_run(task)
            self._deliver(task)

    @staticmethod
    def _checkpoint(task, receipt):
        """Persist observed progress and the owner's next step, never a worker claim."""
        rid = receipt.get('request_id')
        status = receipt.get('status') or 'not_admitted'
        for run in task.run_history:
            if run.run_id == rid:
                run.status = status
                run.error = (receipt.get('result') or {}).get('error')
                if status in {'completed', 'failed', 'cancelled'}:
                    run.completed_at = receipt.get('updated_at') or time.time()
                break
        task.payload['last_progress'] = {
            'request_id': rid, 'request_status': status,
            'observed_at': time.time(), 'task_state': task.state.value,
        }
        task.payload['blocker'] = task.error if task.state in {
            TaskState.PAUSED, TaskState.BLOCKED, TaskState.NEEDS_OWNER, TaskState.FAILED,
            TaskState.QUEUED,
        } else None
        if task.is_terminal:
            next_action = 'Review the retained result' if task.state in {
                TaskState.NEEDS_OWNER, TaskState.BLOCKED, TaskState.FAILED,
            } else 'No further execution'
        elif task.cancellation:
            next_action = 'Reconcile cancellation and owned child receipts; do not replay effects'
        elif task.state == TaskState.PAUSED and not task.provenance.get('authorized'):
            next_action = 'Await approval of this saved objective before execution'
            task.payload['blocker'] = task.error or 'Approval required'
        elif task.state == TaskState.PAUSED:
            next_action = 'Reconcile the existing execution receipt before any retry'
        elif task.state == TaskState.QUEUED:
            next_action = 'Resume the saved task at next_execution using the retained checkpoint'
        else:
            next_action = 'Await the current request receipt and independently verify its result'
        task.payload['next_action'] = next_action

    @staticmethod
    def _settle_run(task):
        run_id = task.payload.get('native_run_id')
        if not run_id:
            return
        from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
        runs = SqliteRunStore()
        run = runs.get(run_id)
        if run and run.state not in {'completed', 'cancelled'}:
            state = 'completed' if task.state in {TaskState.COMPLETED, TaskState.COMPLETED_VERIFIED} else 'cancelled' if task.state == TaskState.CANCELLED else 'failed'
            runs.transition(run_id, state, reason=task.error)

    @staticmethod
    def _execution_root(task):
        """The workspace the turn actually ran in.

        An empty execution workspace means the turn used the effective instance
        workspace (see ``_read_roots``), never the Gateway process cwd, which is
        what ``Path('').resolve()`` would give.
        """
        raw = str((task.payload.get('execution') or {}).get('workspace') or '')
        if not raw:
            try:
                from jaeger_agent.core.workspace import get_effective_workspace_dir
                raw = str(get_effective_workspace_dir() or '')
            except Exception:  # noqa: BLE001
                raw = ''
        return Path(raw).expanduser().resolve() if raw else None

    @staticmethod
    def verify(task, result):
        # Capture scope once. The checked paths and the emitted provenance must
        # describe the same root even if instance binding changes during hashing.
        try:
            root = GatewayTaskOwner._verify_root(task)
        except (OSError, RuntimeError, ValueError):
            if 'research_contract' not in task.payload:
                raise
            root = None
        if 'research_contract' in task.payload:
            from .research import verify_research
            verified, evidence = verify_research(task, result, root)
        else:
            verified, evidence = GatewayTaskOwner._verify_files(task, result, root)
        if not verified:
            return verified, evidence
        execution = task.payload.get('execution') or {}
        workspace = execution.get('workspace') or ''
        marker = execution.get('_instance_defaults') or {}
        instance = not workspace or marker.get('workspace') == workspace
        # Reissue evidence at the owner boundary, never preserve worker metadata.
        # Earlier worker file_sha256 receipts may contain arbitrary extra keys;
        # only this owner's owner_file_sha256 + scope pair can reopen default files.
        receipts = []
        for receipt in evidence:
            # _verify_files returns owner-resolved checked paths, not raw
            # worker claims. Never resolve them again after the file check.
            row = {'kind': 'owner_file_sha256', 'path': receipt['path'], 'sha256': receipt['sha256']}
            if 'research_contract' in task.payload:
                row['research_artifact'] = receipt['research_artifact']
                row['citation_consistency'] = receipt['citation_consistency']
            if instance and root is not None:
                row['owner_artifact_scope'] = {'version': 1, 'mode': 'instance', 'workspace': str(root)}
            receipts.append(row)
        return True, receipts

    @staticmethod
    def _verify_files(task, result, root: Path | None):
        paths = task.payload.get('artifacts') or []
        if paths:
            receipts = []
            if root is None:
                return False, 'No workspace to verify artifacts against'
            for raw in paths:
                path = Path(raw).resolve()
                if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size == 0:
                    return False, f'Required artifact missing or empty: {raw}'
                if path.stat().st_mtime + 1 < task.created_at:
                    return False, f'Artifact predates this task: {raw}'
                receipts.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            return True, receipts
        completion = result.get('task_completion') or {}
        receipts = [r for r in (completion.get('verification_receipts') or []) if r.get('kind') == 'file_sha256']
        if completion.get('ok') and receipts:
            if root is None:
                return False, 'No workspace to verify artifacts against'
            checked = []
            for receipt in receipts:
                raw = receipt.get('resolved') or receipt.get('path') or ''
                path = Path(raw).expanduser()
                path = (root / path).resolve() if not path.is_absolute() else path.resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    return False, f'Verification artifact missing or outside workspace: {raw}'
                if path.stat().st_mtime + 1 < task.created_at or not path.stat().st_size:
                    return False, f'Verification artifact is stale or empty: {raw}'
                if hashlib.sha256(path.read_bytes()).hexdigest() != receipt.get('sha256'):
                    return False, f'Verification artifact changed after the receipt: {raw}'
                checked.append({'path': str(path), 'sha256': receipt['sha256']})
            return True, checked
        named = GatewayTaskOwner._named_path_receipts(task, root)
        if named is not None:
            return named
        return False, UNVERIFIABLE

    @staticmethod
    def _verify_root(task) -> Path | None:
        """The admitted workspace, or (J-087) the owning instance's workspace when the task was admitted
        without one (chat proposals, workflow proposals). The empty path used to resolve to the Gateway's
        cwd, so every receipt the agent wrote in its own workspace read as 'outside workspace'."""
        raw = str((task.payload.get('execution') or {}).get('workspace') or '')
        if not raw:
            # Same root the turn ran in (Gateway & WebUI, 35ef8d96): the effective workspace, then the instance's.
            try:
                from jaeger_agent.core.workspace import get_effective_workspace_dir
                raw = str(get_effective_workspace_dir() or '')
            except Exception:  # noqa: BLE001
                raw = ''
        return Path(raw).expanduser().resolve() if raw else None

    @staticmethod
    def _named_path_receipts(task, root: Path | None):
        """The owner checks the files the request names itself; no worker ritual needed.

        Every named path must exist inside the workspace, be non-empty, and at
        least one must have been written during this task (named inputs predate
        it). Each is hashed. ``None`` means the request names no checkable file.
        """
        from jaeger_ai.core.runtime.autonomous_runner import _required_paths
        names = _required_paths(task.goal or '')
        if not names or root is None:
            return None
        receipts, fresh = [], False
        for raw in names:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                candidates = [(root / path).resolve(), (root.parent / path).resolve()]
                path = next((c for c in candidates if c.exists()), candidates[0])
            else:
                path = path.resolve()
            if not path.is_relative_to(root):
                return None  # outside what the owner may vouch for: not checkable here
            if not path.is_file() or not path.stat().st_size:
                return False, f'Named file missing or empty: {raw}'
            fresh = fresh or path.stat().st_mtime + 1 >= task.created_at
            receipts.append({'kind': 'owner_file_sha256', 'path': str(path),
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        if not fresh:
            return None  # only inputs named: the deliverable is the answer, not a file
        return True, receipts

    def _deliver(self, task):
        if task.payload.get('delivered'):
            return
        if 'research_contract' in task.payload and isinstance(task.result, dict):
            text = str(task.result.get('text') or task.error or task.state.value)
        else:
            text = str(task.result or task.error or task.state.value)
        if task.state not in {TaskState.COMPLETED, TaskState.COMPLETED_VERIFIED}:
            text = f'Background task {task.state.value}: {task.goal}\n{task.error or ""}\n\n{text}'
        receipt = self.gateway.store.deliver_task_result(task.task_id,
            task.notification_policy.recipient_session_id, text, task.state.value)
        if not receipt['replayed']:
            self.gateway.event_bus.fanout(receipt['event'])
        self.store.update_task(task.task_id, lambda t: t.payload.update(delivered=True))

    async def _cancel_owned_children(self, task, receipt):
        # Yielded/retried tasks can have children from an earlier attempt. Walk
        # saved receipts in this task's execution session, including old rows
        # predating run_history, rather than only signalling the latest turn.
        from jaeger_ai.core.gateway.handoff_cancellation import cancel_descendants
        roots = {receipt['request_id']: receipt} if receipt else {}
        original = self.gateway.store.get_request(task.payload.get('original_request_id') or '')
        if original is not None:
            roots[original['request_id']] = original
        prefix = task.task_id + ':'
        for row in self.gateway.store.list_requests():
            rid = row['request_id']
            if (row['session_id'] == 'task:' + task.task_id and rid.startswith(prefix)
                    and rid[len(prefix):].isdigit()
                    and int(rid[len(prefix):]) <= int(task.payload.get('attempt', 0))):
                if not self._continuation_receipt_error(task, row):
                    roots[rid] = row
        results = {}
        for root in roots.values():
            # Same qualified, bounded tree and sticky writer as foreground Stop.
            for child in await cancel_descendants(self.gateway, root, {}):
                results[child['handoff_id']] = child
        return list(results.values())

    async def cancel(self, task_id):
        task = self.store.get_task(task_id)
        if task is None or task.is_terminal:
            return False
        before = self._visible_task(task)
        rid = (task.payload['original_request_id'] if task.provenance.get('turn_owned')
               and task.payload.get('foreground_resume_version') == 1
               else f'{task_id}:{task.payload.get("attempt", 0)}')
        receipt = self.gateway.store.get_request(rid)
        if not task.provenance.get('turn_owned'):
            reason = self._continuation_receipt_error(task, receipt)
            if reason:
                self._retain_foreign_receipt(task_id, reason, cancelled=True)
                retained = self.store.get_task(task_id)
                children = await self._cancel_owned_children(retained, None)
                self.store.update_task(task_id, lambda current:
                    current.payload.update(cancellation_children=children) if not current.is_terminal else None)
                return False
        in_flight = rid in self.gateway._running_tasks or (receipt or {}).get('status') in {'running', 'admitted', 'execution_unknown'}
        if task.payload.get('foreground_resume_version') == 1:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            original = self.gateway.store.get_request(task.payload['original_request_id']) or {}
            native = (receipt or {}).get('native_run_id') or task.payload.get('native_run_id') or original.get('native_run_id')
            if native and EntityRuntime.run_has_indeterminate_effects(native):
                in_flight = True
        def cancel(t):
            if t.is_terminal:
                return
            authoritative_transition(t, TaskState.PAUSED)
            t.cancellation = 'Cancelled by user'
            if in_flight:
                t.error = 'Cancellation requested; waiting for execution/effect receipt'
        task = self.store.update_task(task_id, cancel)
        self.gateway._cancellations.cancel(rid)
        children = await self._cancel_owned_children(task, receipt)
        from jaeger_ai.core.gateway.handoff_cancellation import unconfirmed_ids
        def record_cancellation(current):
            if current.is_terminal or current.payload.get('attempt', 0) != task.payload.get('attempt', 0):
                return
            current.payload['cancellation_children'] = children
            if unconfirmed_ids(children):
                authoritative_transition(current, TaskState.PAUSED,
                    error='Cancellation requested; owned child execution remains unconfirmed')
            elif not in_flight:
                authoritative_transition(current, TaskState.CANCELLED)
            self._checkpoint(current, receipt or {})
        task = self.store.update_task(task_id, record_cancellation)
        for approval in self.gateway.store.list_pending_approvals():
            if (approval.get('metadata') or {}).get('task_id') == task_id:
                self.gateway.store.resolve_approval(approval['approval_id'], approved=False, decision='deny')
        if self._visible_task(task) != before:
            self.gateway.event_bus.publish(task.notification_policy.recipient_session_id, 'task.updated', {'task': task.to_dict()})
        if task.is_terminal:
            self._deliver(task)
        return True
