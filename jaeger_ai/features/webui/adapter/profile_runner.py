"""Profile-owned native execution behind the WebUI runner protocol.

Native Runs retain dispatch/approval/cancellation ownership. RunStore holds
only the browser's replayable event stream and conversation presentation.
"""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any

from jaeger_ai.contract.sessions import native_session_id
from jaeger_ai.core.frameworks.native_runs import Run, Runs, TERMINAL


def canonical_profile(value: Any) -> str:
    """Resolve any spelling of a framework name to its canonical runtime.

    Delegates to the contract so this and the WebUI's profile list can never
    disagree about what ``default`` means. Raises ``ValueError`` rather than
    the contract's ``UnknownFramework`` because callers turn it into a 400.
    """
    from jaeger_ai.contract.frameworks import UnknownFramework, canonical_runtime
    try:
        return canonical_runtime(value or 'jaeger')
    except UnknownFramework as exc:
        raise ValueError(f'No native chat backend configured for profile {value!r}') from exc


def native_session(profile: str, session: str) -> str:
    """The agent-side session id for a browser conversation.

    Delegates to the contract so the shape stays readable by whatever lists
    sessions later — the id is how a row's framework is recovered.
    """
    return native_session_id(profile, session)


class ProfileRunner:
    def __init__(self, store, backends=None):
        self.store = store
        self.backends = backends
        self.managers = {}
        self.lock = threading.RLock()
        self.recover()

    def recover(self):
        # Native ownership remains authoritative after losing an observer.
        # Replay a saved terminal receipt, but never restart native execution.
        for row in self.store.records():
            profile = row.get('profile')
            if profile not in {'hermes', 'openclaw', 'roundtable'} or row.get('terminal_state'):
                continue
            try:
                saved = self.manager(profile).get(row['run_id'])
                state = saved['status']
                payload = {'session_id': row['session_id'], 'stream_id': row['run_id'],
                           'profile': profile, 'status': state}
                if state == 'completed':
                    payload['session'] = self.snapshot(row['session_id'], profile, row['run_id'], row['prompt'], saved['output'])
                else:
                    payload['message'] = 'Runner restarted; inspect the native run before retrying.'
                self.store.append(row['run_id'], 'done' if state == 'completed' else 'apperror', payload)
                self.store.set_state(row['run_id'], status=state, terminal_state=state,
                                     active_controls=[], pending_approval_id=None,
                                     native=saved.get('native', {}), execution_unknown=saved.get('execution_unknown', True))
            except (KeyError, OSError, ValueError):
                self.store.append(row['run_id'], 'apperror', {'message': 'Native run receipt unavailable after restart; execution state is unknown.'})
                self.store.set_state(row['run_id'], status='interrupted', terminal_state='interrupted',
                                     active_controls=[], pending_approval_id=None, execution_unknown=True)

    def manager(self, profile):
        with self.lock:
            if profile not in self.managers:
                root = self.store.root / 'profiles' / profile
                if self.backends is not None:
                    self.managers[profile] = Runs(root, self.backends[profile])
                elif profile == 'roundtable':
                    from jaeger_ai.features.roundtable.service import TableService
                    self.managers[profile] = TableService(root)
                else:
                    from jaeger_ai.core.frameworks.hermes_native import hermes_turn
                    from jaeger_ai.core.frameworks.openclaw_native import openclaw_turn
                    self.managers[profile] = Runs(root, {'hermes': hermes_turn, 'openclaw': openclaw_turn}[profile])
            return self.managers[profile]

    def start(self, request):
        profile = canonical_profile(request.get('profile'))
        session = str(request.get('session_id') or '').strip()
        message = str(request.get('message') or '').strip()
        if not session or not message:
            raise ValueError('message and session_id are required')
        # These native APIs own their container workspaces. The ordinary WebUI
        # default maps to /workspace; do not pretend arbitrary overrides work.
        workspace = str(request.get('workspace') or '').rstrip('/')
        if workspace not in {'', '/workspace', str(Path.home() / 'workspace')}:
            raise ValueError(f'{profile} uses its native /workspace; custom workspace overrides are not supported')
        if request.get('attachments'):
            raise ValueError(f'{profile} attachment transfer is not configured; use native attachment tools')
        model = str(request.get('model') or '').strip()
        provider = str(request.get('provider') or '').strip()
        if model.startswith('@') and ':' in model:
            qualifier, model = model[1:].split(':', 1)
            provider = provider or qualifier
        if provider in {'ollama-local', 'ollama-cloud'}:
            provider = 'ollama'
        manager = self.manager(profile)
        with self.lock:
            rows = self.store.records_for_session(session)
            if any(canonical_profile(row.get('profile')) != profile for row in rows):
                raise ValueError('This conversation belongs to another runtime; start a new conversation for this profile')
            if any(not row.get('terminal_state') for row in rows):
                raise ValueError('This conversation already has an active run')
            if rows and rows[0].get('execution_unknown'):
                try:
                    self.reconcile(rows[0]['run_id'])
                    rows = self.store.records_for_session(session)
                except Exception:
                    pass
            if rows and rows[0].get('execution_unknown'):
                raise ValueError('Native execution state is unknown; reconcile the previous run before retrying')
            def admitted(run):
                self.store.create(run_id=run.id, session_id=session, prompt=message)
                self.store.set_state(run.id, profile=profile, model=model, provider=provider,
                                     webui_profile=str(request.get('profile') or profile),
                                     native_session_id=native_session(profile, session))
            if profile == 'roundtable':
                accepted = manager.start(native_session(profile, session), message, on_admitted=admitted,
                                         model=model or None, provider=provider or None)
            else:
                accepted = manager.start(native_session(profile, session), message,
                                         model=model or None, provider=provider or None, on_admitted=admitted)
            run_id = accepted['run_id']
            threading.Thread(target=self.observe, args=(profile, run_id, session, message), daemon=True).start()
        return {'run_id': run_id, 'stream_id': run_id, 'session_id': session,
                'status': 'running', 'profile': profile, 'started_at': time.time(),
                'active_controls': ['cancel', 'approval']}

    def run(self, run_id):
        status = self.store.status(run_id)
        profile = status.get('profile')
        if profile not in {'hermes', 'openclaw', 'roundtable'}:
            raise KeyError('Not a native profile run')
        run = self.manager(profile).get(run_id)
        if not isinstance(run, Run):
            raise ValueError('Observer restarted; native execution needs reconciliation before control')
        return run

    def reconcile(self, run_id):
        status = self.store.status(run_id)
        profile = status.get('profile')
        if profile not in {'hermes', 'openclaw', 'roundtable'}:
            raise KeyError('Not a native profile run')
        manager = self.manager(profile)
        reconciled = None
        if hasattr(manager, 'reconcile'):
            try:
                reconciled = manager.reconcile(run_id)
            except Exception:
                pass
        if isinstance(reconciled, dict) and not reconciled.get('execution_unknown'):
            terminal_st = reconciled.get('status', 'failed')
            self.store.set_state(
                run_id,
                status=terminal_st,
                terminal_state=terminal_st,
                execution_unknown=False,
                active_controls=[],
                pending_approval_id=None,
            )
            return self.store.status(run_id)
        return status

    def cancel(self, run_id):
        run = self.run(run_id)
        accepted = run.cancel()
        return {'ok': accepted, 'status': 'accepted' if accepted else 'not-active'}

    def approve(self, run_id, approval_id, choice):
        run = self.run(run_id)
        run.approve(approval_id, 'once' if choice == 'session' else choice)
        return {'ok': True, 'status': 'accepted'}

    def snapshot(self, session, profile, run_id, prompt, answer):
        messages = []
        rows = self.store.records_for_session(session)
        current = next((row for row in rows if row['run_id'] == run_id), {})
        for row in rows:
            if row['run_id'] == run_id or row.get('profile') != profile:
                continue
            done = next((e['payload'] for e in reversed(row.get('events', [])) if e.get('event') == 'done'), None)
            if done:
                messages = list(done.get('session', {}).get('messages') or [])
                break
        messages += [{'role': 'user', 'content': prompt, '_ts': time.time()},
                     {'role': 'assistant', 'content': answer, '_ts': time.time()}]
        return {'session_id': session, 'profile': current.get('webui_profile', profile), 'messages': messages,
                'message_count': len(messages), 'title': messages[0]['content'][:80],
                'tool_calls': [], 'updated_at': time.time()}

    def observe(self, profile, run_id, session, prompt):
        try:
            run = self.manager(profile).get(run_id)
            cursor = 0
            while True:
                with run.condition:
                    pending = list(run.events[cursor:])
                    cursor += len(pending)
                    terminal = run.status in TERMINAL
                    if not pending and not terminal:
                        run.condition.wait(.25)
                        continue
                for event in pending:
                    kind = event['event']
                    if kind == 'message.delta':
                        self.store.append(run_id, 'token', {'text': event.get('delta', '')})
                    elif kind == 'reasoning.available':
                        self.store.append(run_id, 'reasoning', {'text': event.get('text', '')})
                    elif kind in {'tool.started', 'tool.completed'}:
                        self.store.append(run_id, 'tool_complete' if kind.endswith('completed') else 'tool',
                            {'name': event.get('tool', 'tool'), 'args': event.get('args', {}),
                             'result': event.get('result'), 'is_error': event.get('status') == 'error'})
                    elif kind == 'approval.request':
                        self.store.set_state(run_id, pending_approval_id=event['approval_id'])
                        self.store.append(run_id, 'approval', {**event, 'run_id': run_id,
                            'session_id': session, 'options': event.get('choices', ['once', 'deny'])})
                    elif kind == 'approval.resolved':
                        self.store.set_state(run_id, pending_approval_id=None)
                    elif kind in {'run.completed', 'run.cancelled', 'run.failed', 'run.interrupted'}:
                        state = kind.split('.')[1]
                        receipt = run.snapshot()
                        payload = {'status': state, 'session_id': session, 'stream_id': run_id,
                                   'profile': profile, 'native': receipt.get('native', {}),
                                   'execution_unknown': receipt.get('execution_unknown', False)}
                        if state == 'completed':
                            payload['session'] = self.snapshot(session, profile, run_id, prompt, run.output)
                        else:
                            payload['message'] = event.get('error') or ('Run cancelled' if state == 'cancelled' else 'Native execution interrupted')
                        self.store.append(run_id, 'done' if state == 'completed' else 'apperror', payload)
                        self.store.set_state(run_id, status=state, terminal_state=state, active_controls=[],
                                             pending_approval_id=None, native=receipt.get('native', {}),
                                             execution_unknown=receipt.get('execution_unknown', False))
                        return
                if terminal:
                    raise RuntimeError('Native stream ended without a terminal event')
        except Exception as exc:
            self.store.append(run_id, 'apperror', {'message': str(exc), 'session_id': session,
                                                 'stream_id': run_id, 'profile': profile})
            self.store.set_state(run_id, status='failed', terminal_state='failed', active_controls=[])
