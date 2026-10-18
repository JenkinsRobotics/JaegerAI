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

from .completion import CompletionError, authoritative_transition
from .models import DurableTask, Goal, NotificationPolicy, Receipt, TaskCard, TaskKind, TaskState
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
               proposal: bool = False, key: str = '') -> dict:
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
        identity = key or json.dumps([context.get('request_id') or '', ' '.join(goal.casefold().split())])
        tid = 'task_' + hashlib.sha256(json.dumps([parent, identity]).encode()).hexdigest()[:24]
        payload = {'execution': execution, 'artifacts': paths}
        task = DurableTask(tid, 'native:jaeger', goal, kind=TaskKind.LONG_RUNNING,
            state=TaskState.QUEUED if approved else TaskState.PAUSED, payload=payload,
            notification_policy=NotificationPolicy(recipient_session_id=parent),
            provenance={'request_id': context.get('request_id'), 'authorized': approved,
                        'source': context.get('source'), 'session_id': parent},
            agent_id=str(context.get('agent_id') or ''), eta=context.get('eta'),
            runner=str(context.get('runner') or 'native'))
        task, replayed = self.store.admit_task(task)
        if not replayed:
            self.gateway.store.ensure_session(f'task:{tid}', title=goal[:100], profile='jaeger', workspace=workspace,
                metadata={'task_id':tid, 'parent_session_id':parent, 'actionable':True})
            self.gateway.event_bus.publish(parent, 'task.created', {'task': task.to_dict()})
            if not approved:
                approval = self.gateway.store.create_approval(kind='background_task',
                    prompt=f'Run proposed background task: {goal}', options=['once', 'deny'],
                    session_id=parent, metadata={'task_id': tid})
                self.gateway.event_bus.publish(parent, 'approval.request', approval)
        return {'ok': True, 'task_id': tid, 'status': task.state.value, 'replayed': replayed,
                'session_id': f'task:{tid}', 'authorized': task.provenance.get('authorized', False)}

    def resolve(self, task_id: str, approved: bool) -> None:
        def update(task):
            if task.is_terminal:
                return
            if task.provenance.get('authorized'):
                # Approval is admission, never permission to replay uncertain effects.
                return
            task.provenance['authorized'] = approved
            authoritative_transition(
                task, TaskState.QUEUED if approved else TaskState.CANCELLED, error=None,
            )
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
                        artifacts: list[str] | None = None, source: str = 'gateway_turn') -> DurableTask:
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
            payload={'turn_card': dict(card_payload), 'execution': dict(execution or {}), 'artifacts': list(artifacts or [])},
            notification_policy=NotificationPolicy(recipient_session_id=parent),
            provenance={'authorized': True, 'turn_owned': True, 'source': source,
                        'session_id': parent, 'request_id': card_payload.get('request_id')},
        )
        task, replayed = self.store.admit_task(task)
        if not replayed:
            self.gateway.event_bus.publish(parent, 'task.created', {'task': task.to_dict()})
        return task

    def settle_turn_card(self, task_id: str, state: TaskState, *, evidence: Any = None,
                         error: str | None = None, result: Any = None) -> DurableTask:
        """The one place a turn-owned task changes state.

        Callers hand over evidence; they never assign ``task.state``. A claim of
        ``completed_verified`` without real evidence becomes ``failed`` here, so
        no caller can report verified work it cannot show.
        """
        def change(task: DurableTask) -> None:
            try:
                authoritative_transition(task, state, evidence=evidence, error=error)
            except CompletionError as exc:
                authoritative_transition(task, TaskState.FAILED, evidence=evidence, error=str(exc))
            if result is not None:
                task.result = result
        task = self.store.update_task(task_id, change)
        parent = task.notification_policy.recipient_session_id or str(task.provenance.get('session_id') or '')
        if parent:
            self.gateway.event_bus.publish(parent, 'task.updated', {'task': task.to_dict()})
        return task

    def open_turn(self, *, session_id: str, request_id: str, text: str, strategy: str,
                  owner: str, workspace: str = '') -> DurableTask:
        """One operational turn becomes one Goal/TaskCard. Replaying the request replays the card."""
        goal = Goal.from_owner(owner=owner or 'owner', objective=text.strip(), session_id=session_id)
        goal.goal_id = f'goal:{request_id}'  # derived, so replaying a request replays its card
        card = TaskCard.open(goal, strategy=strategy, request_id=request_id, task_id=f'turn:{request_id}')
        return self.admit_turn_card(card.to_payload(), execution={'workspace': workspace})

    def close_turn(self, task_id: str, result: dict, *, status: str, identity=None,
                   models: tuple[str, ...] = ()) -> tuple[DurableTask, Receipt]:
        """Verify what the worker returned and settle the card. Workers never choose the state.

        ``status`` is the request's terminal status. Only evidence the owner can
        check (a declared artifact, or a work-ledger receipt for a file that exists
        and matches) reaches ``completed_verified``.
        """
        task = self.store.get_task(task_id)
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
            task = self.settle_turn_card(task_id, state, evidence=evidence, error=error)
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
                if not task.is_terminal:
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
                if receipt.get('status') not in {'completed', 'failed', 'cancelled'}:
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

    def _finished(self, task_id, operation):
        self._active.pop(task_id, None)
        if not operation.cancelled() and operation.exception() is not None:
            logging.getLogger(__name__).error('Task %s will reconcile from its receipt: %s', task_id, operation.exception())

    async def _execute(self, task_id):
        task = self.store.get_task(task_id)
        if task is None or task.is_terminal:
            return
        sid = f'task:{task_id}'
        attempt = int(task.payload.get('attempt', 0))
        rid = f'{task_id}:{attempt}'
        execution = dict(task.payload['execution'])
        execution['is_subordinate'] = True
        execution['options'] = {**(execution.get('options') or {}), 'background': True,
                                'source': 'durable_task', 'task_id': task_id,
                                'verification_error': task.error}
        self.gateway.store.ensure_session(sid, title=task.goal[:100], profile='jaeger',
            workspace=str(execution.get('workspace') or ''),
            metadata={'task_id': task_id, 'parent_session_id': task.notification_policy.recipient_session_id,
                      'actionable': True})
        prompt = ('Execute this authorized durable task fully. Do not queue the same work again. '
                  'Use the real tools, preserve progress, verify the requested outcome, and return the result. '
                  + EVIDENCE_CONTRACT + '\n\n'
                  + task.goal)
        if task.payload.get('artifacts'):
            prompt += '\nRequired result artifacts: ' + json.dumps(task.payload['artifacts'])
        if task.error:
            prompt += '\nOwner verification requires correction: ' + str(task.error)
        if task.result:
            prompt += '\nPrevious checkpoint (continue from verified work):\n' + str(task.result)
        row = self.gateway.store.get_request(rid)
        if task.cancellation and row is None:
            task = self.store.update_task(
                task_id, lambda t: authoritative_transition(t, TaskState.CANCELLED))
            self._deliver(task)
            return
        if row is None:
            admitted = self.gateway.store.admit_request(sid, prompt, request_id=rid, requested=execution)
            if task.payload.get('native_run_id'):
                from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX
                self.gateway.store.bind_native(rid, native_run_id=task.payload['native_run_id'], native_session=f'{OWNER_RUN_SESSION_PREFIX}{sid}')
            self.gateway._start_admitted_turn(admitted, sid, prompt)
        elif row.get('status') in {'admitted', 'running'} and rid not in self.gateway._running_tasks:
            # A persisted admission without dispatch is safe. Unknown effects are
            # recovered separately by the Gateway; never create a fresh run here.
            self.gateway._start_admitted_turn({**row, 'accepted': True}, sid, prompt)
        self.store.update_task(task_id, lambda t: authoritative_transition(t, TaskState.RUNNING)
                               if t.state == TaskState.QUEUED else None)
        operation = self.gateway._running_tasks.get(rid)
        if operation is not None:
            await asyncio.shield(operation)
        row = self.gateway.store.get_request(rid) or {}
        status = row.get('status')
        result = row.get('result') or {}
        if status in {'admitted', 'running'}:
            return
        verified, evidence = self.verify(task, result) if status == 'completed' else (False, '')
        def settle(current):
            if current.state == TaskState.CANCELLED:
                return
            current.result = result.get('output') or result
            if row.get('native_run_id'):
                current.payload['native_run_id'] = row['native_run_id']
            current.payload['verification'] = evidence
            if current.cancellation and status != 'execution_unknown':
                authoritative_transition(current, TaskState.CANCELLED)
            elif verified:
                try:
                    authoritative_transition(
                        current, TaskState.COMPLETED_VERIFIED, evidence=evidence,
                    )
                except CompletionError as exc:
                    authoritative_transition(current, TaskState.FAILED, error=str(exc))
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
        task = self.store.update_task(task_id, settle)
        self.gateway.event_bus.publish(task.notification_policy.recipient_session_id or sid,
                                       'task.updated', {'task': task.to_dict()})
        if task.is_terminal:
            self._settle_run(task)
            self._deliver(task)

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
    def verify(task, result):
        paths = task.payload.get('artifacts') or []
        if paths:
            receipts = []
            root = Path(task.payload['execution']['workspace']).resolve()
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
            root = Path(task.payload['execution'].get('workspace') or '').resolve()
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
            return True, receipts
        named = GatewayTaskOwner._named_path_receipts(task)
        if named is not None:
            return named
        return False, UNVERIFIABLE

    @staticmethod
    def _named_path_receipts(task):
        """The owner checks the files the request names itself; no worker ritual needed.

        Every named path must exist inside the workspace, be non-empty, and at
        least one must have been written during this task (named inputs predate
        it). Each is hashed. ``None`` means the request names no checkable file.
        """
        from jaeger_ai.core.runtime.autonomous_runner import _required_paths
        names = _required_paths(task.goal or '')
        workspace = str((task.payload.get('execution') or {}).get('workspace') or '')
        if not names or not workspace:
            return None
        root = Path(workspace).resolve()
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
        text = str(task.result or task.error or task.state.value)
        if task.state not in {TaskState.COMPLETED, TaskState.COMPLETED_VERIFIED}:
            text = f'Background task {task.state.value}: {task.goal}\n{task.error or ""}\n\n{text}'
        receipt = self.gateway.store.deliver_task_result(task.task_id,
            task.notification_policy.recipient_session_id, text, task.state.value)
        if not receipt['replayed']:
            self.gateway.event_bus.fanout(receipt['event'])
        self.store.update_task(task.task_id, lambda t: t.payload.update(delivered=True))

    async def cancel(self, task_id):
        task = self.store.get_task(task_id)
        if task is None or task.is_terminal:
            return False
        rid = f'{task_id}:{task.payload.get("attempt", 0)}'
        receipt = self.gateway.store.get_request(rid)
        in_flight = rid in self.gateway._running_tasks or (receipt or {}).get('status') in {'running', 'admitted', 'execution_unknown'}
        def cancel(t):
            authoritative_transition(t, TaskState.PAUSED if in_flight else TaskState.CANCELLED)
            t.cancellation = 'Cancelled by user'
            if in_flight:
                t.error = 'Cancellation requested; waiting for execution/effect receipt'
        task = self.store.update_task(task_id, cancel)
        self.gateway._cancellations.cancel(rid)
        for approval in self.gateway.store.list_pending_approvals():
            if (approval.get('metadata') or {}).get('task_id') == task_id:
                self.gateway.store.resolve_approval(approval['approval_id'], approved=False, decision='deny')
        self.gateway.event_bus.publish(task.notification_policy.recipient_session_id, 'task.updated', {'task': task.to_dict()})
        if task.is_terminal:
            self._deliver(task)
        return True
