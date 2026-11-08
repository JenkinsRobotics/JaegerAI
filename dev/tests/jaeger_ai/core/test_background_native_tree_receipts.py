"""No native delegated tree may hide behind a returned background parent."""
import hashlib
import json
import os

import pytest
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.memory import sqlite_store
from jaeger_ai.core.gateway.owner_receipts import encoded
from dev.tests.jaeger_ai.core.test_background_terminal_journal import (
    env, crash, journal, restart, pending_effect,
)


def child(parent, state='active', *, relation='delegate'):
    commitments, runs = SqliteCommitmentStore(), SqliteRunStore()
    commitment = commitments.create('Synthetic native child', kind='delegation')
    run = runs.create(commitment.id, owner_pid=os.getpid(), parent_run_id=parent, relation=relation)
    runs.transition(run.id, 'active')
    runs.checkpoint(run.id, {'synthetic_child': True})
    if state == 'completed':
        runs.transition(run.id, 'completed')
    elif state == 'pending':
        pending_effect(run.id)
    return run.id


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['seal', 'projection'])
@pytest.mark.parametrize('state', ['active', 'completed', 'pending'])
@pytest.mark.parametrize('link', ['parent', 'root-only'])
async def test_native_descendants_block_seal_and_recovery(env, monkeypatch, boundary, state, link):
    def add(native):
        ident = child(native, state)
        if link == 'root-only':
            # A retained descendant still names the accepted root after its
            # immediate parent row disappears or lies outside accepted runs.
            with sqlite_store.writer() as conn:
                conn.execute("UPDATE runs SET parent_run_id='unaccepted-parent' WHERE id=?", (ident,))
        return ident
    if boundary == 'seal':
        produce = env.runtime.before_answer
        env.runtime.before_answer = lambda native: (add(native), produce(native))
        await env.app.task_owner._execute(env.tid)
        assert journal(env)['terminal_json'] is None
        assert env.app.task_owner.store.get_task(env.tid).state.value == ('completed_verified' if state == 'completed' else 'paused')
    else:
        await crash(env, monkeypatch)
        add(env.store.get_request(env.rid)['native_run_id'])
        for _ in range(2):
            app = restart(env)
            assert app._recover_sealed_owner_results() == 0
            assert app.store.get_request(env.rid)['status'] == 'execution_unknown'
        assert env.runtime.calls == 1


async def first_rotated_attempt(env):
    earlier = []
    def rotate(native):
        if not earlier:
            earlier.append(native)
            SqliteRunStore().transition(native, 'completed')
    env.runtime.before_answer = rotate
    env.runtime.answers = [('First run returned, continue', None), ('Partial progress', 'yielded')]
    await env.app.task_owner._execute(env.tid)
    task = env.app.task_owner.store.get_task(env.tid)
    assert task.payload['attempt'] == 1
    assert len(task.payload['background_admissions'][env.rid]['native_run_ids']) == 2
    return earlier[0]


def handoff(env, reference, *, binding=False):
    env.store.save_handoff({'id': 'earlier-child', 'from_agent_id': 'native:jaeger',
        'to_agent_id': 'synthetic-child', 'parent_run_id': None if binding else reference,
        'metadata': {'parent_binding': {'request_id': reference}} if binding else {},
        'task': 'Earlier attempt child', 'status': 'completed'})


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', [None, 'native', 'native-root', 'handoff-native', 'handoff-request',
                                  'handoff-turn', 'handoff-binding', 'pending-effect', 'missing-checkpoint'])
@pytest.mark.parametrize('boundary', ['seal', 'projection'])
async def test_every_prior_attempt_remains_in_completion_scope(env, monkeypatch, fault, boundary):
    produce = env.runtime.before_answer
    earlier = await first_rotated_attempt(env)
    prior_rid = env.rid
    prior = env.store.get_request(prior_rid)
    def change():
        if fault in {'native', 'native-root'}:
            ident = child(earlier, 'completed')
            if fault == 'native-root':
                with sqlite_store.writer() as conn:
                    conn.execute("UPDATE runs SET parent_run_id='unaccepted-parent' WHERE id=?", (ident,))
        elif fault and fault.startswith('handoff-'):
            reference = {'handoff-native': earlier, 'handoff-request': prior_rid,
                         'handoff-turn': prior['turn_id'], 'handoff-binding': prior_rid}[fault]
            handoff(env, reference, binding=fault == 'handoff-binding')
        elif fault == 'pending-effect':
            pending_effect(earlier)
        elif fault == 'missing-checkpoint':
            with sqlite_store.writer() as conn:
                conn.execute('DELETE FROM checkpoints WHERE run_id=?', (earlier,))
    def complete(native):
        assert native != earlier
        if boundary == 'seal': change()
        produce(native)
    env.runtime.before_answer = complete
    env.runtime.answers = [('Finished answer.', None)]
    env.rid = env.tid+':1'
    if boundary == 'projection':
        # The first attempt made two model calls; crash helper expects exactly
        # the one call in this final attempt, without losing retained runs.
        env.runtime.calls = 0
        await crash(env, monkeypatch)
        change()
        for attempt in range(2):
            app = restart(env)
            assert app._recover_sealed_owner_results() == (int(fault is None) if attempt == 0 else 0)
            assert app.store.get_request(env.rid)['status'] == ('completed' if fault is None else 'execution_unknown')
        assert env.runtime.calls == 1
    else:
        await env.app.task_owner._execute(env.tid)
        assert bool(journal(env)['terminal_json']) == (fault is None)
        assert env.runtime.calls == 3
        if fault in {'pending-effect', 'missing-checkpoint'}:
            assert env.app.task_owner.store.get_task(env.tid).state.value == 'paused'
    if fault is None:
        proof = env.store.owner_request_receipt(env.rid)
        assert proof['version'] == 4
        assert len(proof['native_run_ids']) == 1
        assert proof['task_native_run_ids'] == [earlier, prior['native_run_id']]
        assert set(proof['task_admissions']) == {prior_rid, env.rid}


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['seal', 'projection'])
async def test_child_arriving_during_file_verification_is_rechecked(env, monkeypatch, boundary):
    from jaeger_ai.core.tasks.owner import GatewayTaskOwner
    verify = GatewayTaskOwner.verify
    if boundary == 'projection':
        await crash(env, monkeypatch)
    added = []
    def verify_with_child(task, result):
        outcome = verify(task, result)
        if not added:
            native = env.store.get_request(env.rid)['native_run_id']
            added.append(child(native, 'pending'))
        return outcome
    monkeypatch.setattr(GatewayTaskOwner, 'verify', staticmethod(verify_with_child))
    if boundary == 'seal':
        await env.app.task_owner._execute(env.tid)
        assert journal(env)['terminal_json'] is None
    else:
        app = restart(env)
        assert app._recover_sealed_owner_results() == 0
        assert app.store.get_request(env.rid)['status'] == 'execution_unknown'


@pytest.mark.asyncio
async def test_unrelated_native_work_does_not_block_same_task_root_completion(env):
    commitments, runs = SqliteCommitmentStore(), SqliteRunStore()
    other = runs.create(commitments.create('Other task', kind='synthetic').id, owner_pid=os.getpid())
    runs.transition(other.id, 'active')
    child(other.id, 'pending')
    await env.app.task_owner._execute(env.tid)
    assert journal(env)['terminal_json']
    assert env.app.task_owner.store.get_task(env.tid).state.value == 'completed_verified'


@pytest.mark.asyncio
async def test_v1_seal_without_task_tree_capture_is_not_retroactively_upgraded(env, monkeypatch):
    await crash(env, monkeypatch)
    proof = json.loads(journal(env)['terminal_json'])
    proof['version'] = 1
    proof.pop('task_admissions')
    proof.pop('task_native_run_ids')
    serialized = encoded(proof)
    with env.store._immediate() as conn:
        conn.execute('UPDATE background_request_journal SET terminal_json=?, terminal_sha256=? WHERE request_id=?',
            (serialized, hashlib.sha256(serialized.encode()).hexdigest(), env.rid))
    app = restart(env)
    assert app._recover_sealed_owner_results() == 0
    assert app.store.get_request(env.rid)['status'] == 'execution_unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['child-pending', 'child-active', 'root-pending'])
async def test_normal_settlement_rechecks_tree_after_request_projection(env, monkeypatch, fault):
    persist = env.app._persist_terminal
    def project_then_change(*args, **kwargs):
        persist(*args, **kwargs)
        native = env.store.get_request(env.rid)['native_run_id']
        if fault == 'root-pending':
            pending_effect(native)
        else:
            child(native, 'pending' if fault == 'child-pending' else 'active')
    monkeypatch.setattr(env.app, '_persist_terminal', project_then_change)
    await env.app.task_owner._execute(env.tid)
    assert env.store.get_request(env.rid)['status'] == 'completed'
    assert env.app.task_owner.store.get_task(env.tid).state.value == 'paused'
    assert env.runtime.calls == 1


@pytest.mark.asyncio
async def test_completed_native_child_does_not_hide_pending_grandchild(env):
    produce = env.runtime.before_answer
    def descendants(native):
        middle = child(native, 'completed')
        child(middle, 'pending')
        produce(native)
    env.runtime.before_answer = descendants
    await env.app.task_owner._execute(env.tid)
    assert journal(env)['terminal_json'] is None
    assert env.app.task_owner.store.get_task(env.tid).state.value == 'paused'


@pytest.mark.asyncio
@pytest.mark.parametrize('lineage', ['accepted-root', 'foreign-parent', 'foreign-root', 'cycle', 'delegate'])
async def test_only_same_task_accepted_root_lineage_can_seal(env, lineage):
    produce = env.runtime.before_answer
    earlier = await first_rotated_attempt(env)
    def change(native):
        with sqlite_store.writer() as conn:
            conn.execute('UPDATE runs SET parent_run_id=?, root_run_id=?, relation=? WHERE id=?',
                ('foreign' if lineage == 'foreign-parent' else earlier,
                 'foreign' if lineage == 'foreign-root' else earlier,
                 'delegate' if lineage == 'delegate' else 'root', native))
            if lineage == 'cycle':
                conn.execute('UPDATE runs SET parent_run_id=? WHERE id=?', (native, earlier))
        produce(native)
    env.runtime.before_answer = change
    env.runtime.answers = [('Finished answer.', None)]
    await env.app.task_owner._execute(env.tid)
    env.rid = env.tid+':1'
    assert bool(journal(env)['terminal_json']) == (lineage == 'accepted-root')
