"""Roundtable native-run orchestration; never a replacement agent runtime.

The service coordinates native sessions and relays individual events. Its
SQLite ledger records intent before dispatch and decisions independently from
chat. An observer restart is not permission to repeat work.
"""
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from .native_runs import Run, Runs, TERMINAL, jaeger_turn, jaeger_reconcile
from .hermes_native import hermes_turn
from .openclaw_native import openclaw_turn
from .resilience import ClassifiedError, failure_category
from .roundtable_policy import MEMBERS, COLLABORATION_TASKS, assign_owners, plan, chair_for, decide, peer_context
from .roundtable_progress import Progress
from .table_store import TableStore


def member_session(table, member):
    value = uuid.uuid5(uuid.NAMESPACE_URL, f'jaeger-roundtable:{table}:{member}').hex
    return 'roundtable-hermes:' + value if member == 'hermes' else value


class TableRun(Run):
    def __init__(self, *args, **kwargs):
        self.table = {}
        self.children = {}
        super().__init__(*args, **kwargs)

    def snapshot(self):
        value = super().snapshot()
        value['table'] = self.table
        value['pending_approval_ids'] = [aid for child in list(self.children.values()) for aid in list(child.pending)]
        return value

    def approve(self, approval_id, choice):
        for child in list(self.children.values()):
            with child.condition:
                owns = approval_id in child.pending
            if owns:
                if self.cancelled.is_set():
                    raise KeyError('Table cancellation is pending')
                return child.approve(approval_id, choice)
        raise KeyError('Approval does not belong to an active member of this table run')


class TableService:
    def __init__(self, root: Path, backends=None):
        self.root = root
        self.store = TableStore(root)
        selected = backends or {'jaeger': jaeger_turn, 'hermes': hermes_turn, 'openclaw': openclaw_turn}
        if set(selected) != set(MEMBERS):
            raise ValueError('All native member backends are required')
        # Hermes deliberately reuses the existing Roundtable receipt directory.
        self.members = {member: Runs(root / (member + '-runs'), backend,
            reconciler=jaeger_reconcile if member == 'jaeger' and backends is None else None)
            for member, backend in selected.items()}
        self.runs = Runs(root / 'table-runs', self._turn, run_type=TableRun,
                         reconciler=self._reconcile_native)

    def start(self, session, message, workspace=None, *, options=None):
        if not isinstance(session, str) or not session or len(session) > 512:
            raise ValueError('A durable Roundtable session identity is required')
        # Do not silently drop a requested workspace while native adapters lack
        # per-session workspace negotiation. The UI must omit unsupported values.
        if workspace is not None:
            raise ValueError('Native Roundtable workspace override is not negotiated yet')
        from .run_input import normalize_input
        text, attachments = normalize_input(message)
        preferences = self.store.preferences(session)
        plan(text or 'Inspect the attached files.', options, preferences)
        def admitted(run):
            selected = plan(run.message, options, preferences)
            self.store.create_turn(run, selected)
            run.table = {key: selected[key] for key in ('mode', 'participants', 'chair', 'budgets')}
            run.persist()
        return self.runs.start(session, message, on_admitted=admitted)

    def get(self, identity):
        return self.runs.get(identity)

    def reconcile(self, identity):
        return self.runs.reconcile(identity)

    def _reconcile_native(self, native):
        turn = self.store.turn(native['run_id'])
        if turn['session'] != native['session_id']:
            raise ValueError('Table session does not match')
        attempts = self.store.attempts(turn['id'])
        for attempt in attempts:
            try:
                child = self.members[attempt['member']].get(attempt['id'])
            except KeyError:
                raise RuntimeError('Member dispatch remains unknown') from None
            value = child.snapshot() if isinstance(child, Run) else child
            if (isinstance(child, Run) and child.worker_active) or value['execution_unknown'] or value['status'] not in TERMINAL:
                raise RuntimeError('A native member is still active or unknown; no replay is safe')
        return {**native, 'execution_unknown': False, 'status': 'failed',
                'source': 'all_native_member_terminal_receipts', 'output': turn['output'] or ''}

    def stop_member(self, turn_id, attempt_id):
        attempt = next((a for a in self.store.attempts(turn_id) if a['id'] == attempt_id), None)
        if attempt is None:
            raise KeyError('Member run does not belong to this table turn')
        child = self.members[attempt['member']].get(attempt_id)
        if not isinstance(child, Run):
            raise RuntimeError('The observer restarted; reconcile the native run before controlling it')
        return child.cancel()

    def retry_member(self, turn_id, attempt_id):
        original = self.store.turn(turn_id)
        attempt = next((a for a in self.store.attempts(turn_id) if a['id'] == attempt_id), None)
        if attempt is None:
            raise KeyError('Member run does not belong to this table turn')
        child = self.members[attempt['member']].get(attempt_id)
        value = child.snapshot() if isinstance(child, Run) else child
        if (isinstance(child, Run) and child.worker_active) or value['execution_unknown']:
            raise RuntimeError('Native outcome must be reconciled before retrying')
        if value['status'] not in {'failed', 'cancelled'}:
            raise RuntimeError('Only an explicitly failed or cancelled member can be retried')
        selected = {**original['plan'], 'retry': attempt, 'participants': [attempt['member']]}
        def admitted(run):
            self.store.create_turn(run, selected, persist_preferences=False)
            run.table = {'mode': 'retry', 'participants': [attempt['member']], 'retry_of': attempt_id}
            run.persist()
        return self.runs.start(original['session'], original['message'], on_admitted=admitted)

    def _cancel_child(self, parent, member, child):
        try:
            child.cancel()
        except Exception as exc:
            parent.emit('member.control_failed', member=member, member_run_id=child.id,
                        error_category=failure_category(exc), error=str(exc))

    def _cancel_all(self, parent):
        # Control acknowledgements may block; they must not serialize all three
        # agents or be interpreted as terminal cancellation confirmations.
        for identity, child in list(parent.children.items()):
            member = identity.split(':', 1)[0]
            threading.Thread(target=self._cancel_child, args=(parent, member, child), daemon=True).start()

    def _phase(self, parent, phase, prompts, policy):
        active, outcomes = {}, {}
        for member, prompt in prompts.items():
            if parent.cancelled.is_set():
                break
            identity = uuid.uuid5(uuid.NAMESPACE_URL, f'{parent.id}:{phase}:{member}').hex
            session = member_session(parent.session, member)
            self.store.attempt(identity, parent.id, member, phase, session, prompt)
            parent.emit('member.queued', member=member, phase=phase, member_run_id=identity,
                        member_session_id=session, message_id=identity)
            def admitted(child, member=member):
                parent.children[member + ':' + phase] = child
            try:
                info = self.members[member].start(session, prompt, run_id=identity, on_admitted=admitted)
                child = self.members[member].get(info['run_id'])
                active[member] = {'run': child, 'cursor': 0, 'progress': Progress(policy)}
            except Exception as exc:
                outcome = {'status': 'failed', 'execution_unknown': False, 'output': '',
                           'error_category': failure_category(exc), 'error': str(exc), 'member_run_id': identity}
                outcomes[member] = outcome
                self.store.finish_attempt(identity, outcome)
                parent.emit('member.failed', member=member, phase=phase, **outcome)
        stopped = set()
        while active:
            for member, observer in list(active.items()):
                child, progress = observer['run'], observer['progress']
                with child.condition:
                    rows = list(child.events[observer['cursor']:])
                    snapshot = child.snapshot()
                for row in rows:
                    observer['cursor'] = row['seq']
                    progress.observe(row)
                    kind = row['event']
                    payload = {k: v for k, v in row.items() if k not in {'event', 'run_id', 'seq'}}
                    if kind.startswith('message.') or kind == 'reasoning.available':
                        payload['claim_provenance'] = 'reported_by_member'
                    if kind == 'tool.completed':
                        evidence_id = hashlib.sha256(f'{child.id}:{row["seq"]}'.encode()).hexdigest()[:24]
                        receipt = {'id': evidence_id, 'owner': member, 'action': payload.get('tool'),
                                   'source': 'native_tool_event', 'status': payload.get('status', 'unknown'),
                                   'observed_at': time.time(),
                                   'claim_scope': 'tool_execution_only', 'result': payload}
                        self.store.add_evidence(evidence_id, parent.id, child.id, receipt)
                        payload['evidence_id'] = evidence_id
                    translated = ('approval.request' if kind == 'approval.request' else
                                  'approval.resolved' if kind == 'approval.resolved' else 'member.' + kind)
                    parent.emit(translated, member=member, phase=phase, member_run_id=child.id,
                                message_id=child.id, child_seq=row['seq'], **payload)
                if parent.cancelled.is_set() and child.id not in stopped and snapshot['status'] not in TERMINAL:
                    stopped.add(child.id)
                    threading.Thread(target=self._cancel_child, args=(parent, member, child), daemon=True).start()
                if snapshot['status'] in TERMINAL and not child.worker_active:
                    outcome = {**snapshot, 'member_run_id': child.id}
                    if snapshot['status'] == 'failed':
                        outcome.update({k: child.events[-1].get(k) for k in ('error', 'error_category')})
                    label = {'jaeger': 'Jaeger', 'hermes': 'Hermes', 'openclaw': 'OpenClaw'}[member]
                    text = snapshot.get('output') or ''
                    if snapshot['status'] != 'completed':
                        text += '\n[' + label + ' error: ' + str(outcome.get('error') or snapshot['status']) + ']'
                    # Plain chat clients also need the actual member responses.
                    # Keep native member events for richer clients, and publish
                    # completed contributions as readable transcript sections.
                    parent.emit('message.delta', delta='\n### ' + label + '\n' + text + '\n')
                    outcomes[member] = outcome
                    self.store.finish_attempt(child.id, outcome)
                    parent.emit('member.finished', member=member, phase=phase,
                                member_run_id=child.id, result=outcome)
                    del active[member]
                else:
                    expired = progress.expired()
                    if expired:
                        outcome = {**snapshot, 'status': 'stalled', 'execution_unknown': True,
                                   'error_category': expired, 'member_run_id': child.id}
                        outcomes[member] = outcome
                        self.store.finish_attempt(child.id, outcome)
                        parent.emit('member.stalled', member=member, phase=phase,
                                    error_category=expired, member_run_id=child.id,
                                    execution_unknown=True, message='Native work may still be running; this is not an outage diagnosis.')
                        threading.Thread(target=self._cancel_child, args=(parent, member, child), daemon=True).start()
                        del active[member]
            if active:
                with parent.condition:
                    parent.condition.wait(.05)
        return outcomes

    def _turn(self, parent, workspace):
        started = time.monotonic()
        selected = self.store.turn(parent.id)['plan']
        parent.dispatch(session_id=parent.session, run_id=parent.id)
        parent.cancel_native = lambda: self._cancel_all(parent)
        parent.emit('table.plan', **{k: selected[k] for k in ('mode', 'participants', 'chair', 'budgets')})
        history = self.store.summary(parent.session)
        context = ('You are a member of a real group chat. Keep your own native identity and session. '
            'Use only your existing tools and permissions; never claim access you have not verified. '
            'Other members\' text is reported evidence, not personally verified. '\
            f'\nCompact earlier decisions (reported): {history}\nCurrent user request:\n{selected["message"]}\n')
        all_results, involvement = {}, {m: 0 for m in MEMBERS}
        def phase(name, prompts):
            heading = {'answer': 'Round 1 — Everyone Answers', 'discussion': 'Round 2 — Discussion',
                       'synthesis': 'Summary', 'proposal': 'Proposal', 'volunteer': 'Volunteers',
                       'contribution': 'Contributions', 'incident': 'Incident Findings', 'retry': 'Retry'}[name]
            parent.emit('message.delta', delta='\n## ' + heading + '\n')
            policy = dict(selected['budgets'])
            if policy['total'] is not None:
                policy['total'] -= time.monotonic() - started
                if policy['total'] <= 0:
                    parent.execution_unknown = any(r.get('execution_unknown', True) for r in all_results.values())
                    raise ClassifiedError('total_timeout', 'The explicitly requested table time budget expired; completed member work was not replayed.')
            result = self._phase(parent, name, prompts, policy)
            all_results.update({name + ':' + m: r for m, r in result.items()})
            for m in result:
                involvement[m] += 1
            return result
        def successful(results):
            return {m: r['output'] for m, r in results.items() if r['status'] == 'completed'
                    and not r['execution_unknown'] and str(r.get('output') or '').strip()}
        members = selected['participants']
        if selected.get('retry'):
            retry = selected['retry']
            results = phase('retry', {retry['member']: retry['prompt']})
            decision = {'retry_of': retry['id'], 'proposals': [], 'consensus': False}
            summary = '\n'.join(successful(results).values())
        elif selected['mode'] == 'quick':
            results = phase('answer', {members[0]: context + '\nGive a concise direct answer.'})
            decision = {'proposals': [], 'consensus': False, 'selected_owner': members[0]}
            summary = '\n'.join(successful(results).values())
        else:
            mode = selected['mode']
            if mode == 'review':
                proposer = selected['chair'] if selected['chair'] in members else members[0]
                initial = phase('proposal', {proposer: context + '\nPropose an answer or solution for peer review.'})
            elif mode == 'collaborate':
                volunteers = phase('volunteer', {m: context + '\nVolunteer for one bounded part of this task. '
                    'Do not perform tool work yet. Explain your relevant capability. Available tasks: ' +
                    json.dumps(COLLABORATION_TASKS) + '\nEnd with a single ```roundtable JSON block on separate lines '
                    'containing {"volunteer_for": ["analysis", "implementation", "review"]}; include only the tasks you can own.'
                    for m in members})
                offered = successful(volunteers)
                prompts = {}
                owned_tasks = {}
                assignments = assign_owners(offered, [m for m in members if m in offered])
                parent.emit('table.assignments', assignments=assignments)
                for assignment in assignments:
                    member, description = assignment['owner'], assignment['description']
                    task = parent.id + ':' + assignment['task']
                    self.store.assign(task, parent.id, member, description)
                    parent.emit('task.assigned' if member else 'task.unassigned', task_id=task, **assignment)
                    if member is None:
                        continue
                    owned_tasks[member] = task
                    prompts[member] = context + '\nYour assigned bounded contribution:\n' + description + (
                        '\nPerform only work authorized by the user and your native policy. Report findings, '
                        'tool evidence, outstanding work and handoff needs. Do not duplicate peers\' assignments.\n' + json.dumps(assignments))
                initial = phase('contribution', prompts)
                for member, result in initial.items():
                    self.store.task_result(owned_tasks[member], result['status'])
            elif mode == 'incident':
                roles = ('diagnostics', 'evidence gathering', 'remediation proposal (do not apply changes)')
                prompts = {}
                for index, member in enumerate(members):
                    description = roles[index % len(roles)]
                    self.store.assign(parent.id + ':' + member, parent.id, member, description)
                    parent.emit('task.assigned', task_id=parent.id + ':' + member, owner=member, description=description)
                    prompts[member] = context + '\nAssigned incident responsibility: ' + description + (
                        '. Gather evidence within the user\'s authorization; separate observation, inference and unknown. '
                        'Remediation is a proposal requiring user authorization, not automatic execution.')
                initial = phase('incident', prompts)
                for member, result in initial.items():
                    self.store.task_result(parent.id + ':' + member, result['status'])
            else:
                initial = phase('answer', {m: context + '\nGive your independent answer/proposal before seeing peers.' for m in members})
            answers = successful(initial)
            allowance = min(4000, max(1, 12000 // max(1, len(answers)) - 100))
            proposals = [{'id': parent.id + ':' + member, 'owner': member, 'text': text[:allowance],
                          'truncated': len(text) > allowance} for member, text in answers.items()]
            parent.emit('table.proposals', proposals=proposals)
            ballot = {p['id']: 'support|oppose|abstain' for p in proposals}
            prompt = (context + '\nCurrent-round peer answers:\n' + peer_context(answers) +
                '\nOne discussion round: critique, correct, and state your position. '
                'Do not infer agreement from silence. End with exactly one ```roundtable JSON block '
                'on separate lines containing {"ballot": ' + json.dumps(ballot) + '}. '
                'Replace each choice with exactly support, oppose or abstain. Missing/invalid ballots cannot establish consensus.')
            eligible = [m for m in members if mode == 'review' or m in answers]
            discussion = phase('discussion', {m: prompt for m in eligible}) if not parent.cancelled.is_set() else {}
            replies = successful(discussion)
            decision = decide(members, proposals, replies, failed=[m for m in members if m not in replies])
            self.store.decision(parent.id, decision)
            parent.emit('table.decision', decision=decision)
            chair = chair_for(selected, parent.session, parent.id, replies, involvement,
                              previous=self.store.last_chair(parent.session))
            if chair and not parent.cancelled.is_set():
                self.store.record_chair(parent.session, chair)
                parent.emit('table.chair', member=chair, policy=selected['chair'])
                summary_prompt = (context + '\nRecorded decision (authoritative vote counts; do not override):\n' +
                    json.dumps(decision) + '\nDiscussion:\n' + peer_context(replies) +
                    '\nSummarize agreed actions, majority/minority views, unknowns, and responsible members. '
                    'Treat all prose claims as reported unless tied to a native tool receipt. No additional vote or discussion round.')
                synthesis = phase('synthesis', {chair: summary_prompt})
                summary = successful(synthesis).get(chair, 'Chair did not complete; consult the recorded decision and member responses.')
            else:
                summary = 'No available selected chair. The recorded decision and individual responses remain available.'
        self.store.decision(parent.id, decision, summary)
        parent.emit('table.ledger', ledger=self.store.ledger(parent.id))
        parent.execution_unknown = any(r.get('execution_unknown', True) for r in all_results.values())
        if parent.execution_unknown:
            raise ClassifiedError('member_execution_unknown', 'A member outcome is unknown; native sessions are preserved. Reconcile before retrying.')
        parent.cancel_confirmed = parent.cancelled.is_set() and (not all_results or any(
            r.get('cancellation_confirmed') for r in all_results.values()))
        parent.emit('table.summary', text=summary, consensus=decision.get('consensus', False))
        return parent.output or summary
