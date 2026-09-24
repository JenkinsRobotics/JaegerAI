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

from .models import DurableTask, NotificationPolicy, TaskKind, TaskState
from .store import SqliteDurableTaskStore


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
        identity = key or json.dumps([context.get('request_id') or '', ' '.join(goal.casefold().split())])
        tid = 'task_' + hashlib.sha256(json.dumps([parent, identity]).encode()).hexdigest()[:24]
        payload = {'execution': execution, 'artifacts': sorted(set(paths))}
        task = DurableTask(tid, 'native:jaeger', goal, kind=TaskKind.LONG_RUNNING,
            state=TaskState.QUEUED if approved else TaskState.PAUSED, payload=payload,
            notification_policy=NotificationPolicy(recipient_session_id=parent),
            provenance={'request_id': context.get('request_id'), 'authorized': approved,
                        'source': context.get('source'), 'session_id': parent})
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
            task.state = TaskState.QUEUED if approved else TaskState.CANCELLED
            task.error = None
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
            if task.is_terminal:
                try:
                    self._deliver(task)
                except ValueError:
                    # A deleted parent cannot consume the scheduler's whole tick.
                    # Keep the result available through /v1/tasks/{id}.
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
                  'Use work_ledger with verify={kind: paths_exist, paths: [your result files]} and complete_task. '
                  'A count-only ledger or a successful command is not a verified deliverable.\n\n'
                  + task.goal)
        if task.payload.get('artifacts'):
            prompt += '\nRequired result artifacts: ' + json.dumps(task.payload['artifacts'])
        if task.error:
            prompt += '\nOwner verification requires correction: ' + str(task.error)
        if task.result:
            prompt += '\nPrevious checkpoint (continue from verified work):\n' + str(task.result)
        row = self.gateway.store.get_request(rid)
        if task.cancellation and row is None:
            task = self.store.update_task(task_id, lambda t: setattr(t, 'state', TaskState.CANCELLED))
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
        self.store.update_task(task_id, lambda t: setattr(t, 'state', TaskState.RUNNING)
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
                current.state = TaskState.CANCELLED
            elif verified:
                current.state = TaskState.COMPLETED
                current.error = None
            elif status == 'cancelled':
                current.state = TaskState.CANCELLED
            elif status == 'execution_unknown':
                current.state = TaskState.PAUSED
                current.error = 'Execution outcome unknown; reconcile effects before retry'
            elif result.get('halt_reason') == 'yielded':
                current.payload['attempt'] = attempt + 1
                current.state = TaskState.QUEUED
                current.next_execution = time.time() + 1
            elif current.retry_policy.can_retry():
                current.retry_policy.current_retries += 1
                current.payload['attempt'] = attempt + 1
                current.state = TaskState.QUEUED
                current.next_execution = time.time() + current.retry_policy.backoff_seconds
                current.error = str(result.get('error') or evidence or 'Outcome not verified')
            else:
                current.state = TaskState.FAILED
                current.error = str(result.get('error') or evidence or 'Outcome not verified after retries')
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
            state = 'completed' if task.state == TaskState.COMPLETED else 'cancelled' if task.state == TaskState.CANCELLED else 'failed'
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
                if path.stat().st_mtime < task.created_at:
                    return False, f'Artifact predates this task: {raw}'
                receipts.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            return True, receipts
        completion = result.get('task_completion') or {}
        receipts = [r for r in (completion.get('verification_receipts') or []) if r.get('kind') == 'file_sha256']
        if completion.get('ok') and receipts:
            root = Path(task.payload['execution'].get('workspace') or '').resolve()
            for receipt in receipts:
                raw = receipt.get('path') or ''
                path = Path(raw).expanduser()
                path = (root / path).resolve() if not path.is_absolute() else path.resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    return False, f'Verification artifact missing or outside workspace: {raw}'
                if path.stat().st_mtime < task.created_at or not path.stat().st_size:
                    return False, f'Verification artifact is stale or empty: {raw}'
                if hashlib.sha256(path.read_bytes()).hexdigest() != receipt.get('sha256'):
                    return False, f'Verification artifact changed after the receipt: {raw}'
            return True, receipts
        return False, 'No objective verification receipt; continue execution and verify the result'

    def _deliver(self, task):
        if task.payload.get('delivered'):
            return
        text = str(task.result or task.error or task.state.value)
        if task.state != TaskState.COMPLETED:
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
            t.state = TaskState.PAUSED if in_flight else TaskState.CANCELLED
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
