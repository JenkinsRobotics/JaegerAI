"""Actual TaskOwner Stop must retain uncertainty from the accepted operation graph."""
from dataclasses import asdict
import json

import pytest
from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
from dev.tests.jaeger_ai.core.test_background_terminal_journal import env,pending_effect
from dev.tests.jaeger_ai.core.test_background_completion_graph import first_rotation, separate_child


@pytest.mark.asyncio
@pytest.mark.parametrize('fault,truncate',[(None,False),('earlier',False),('indirect',False),('earlier',True),('indirect',True)])
async def test_stop_does_not_confirm_cancelled_with_retained_pending_graph(env,monkeypatch,fault,truncate):
    earlier=await first_rotation(env)
    prior=env.rid
    calls=env.runtime.calls
    if fault=='earlier':pending_effect(earlier)
    elif fault=='indirect':separate_child(env,earlier,True)
    if truncate:
        env.app.task_owner.store.update_task(env.tid,
            lambda task:task.payload['background_admissions'][prior]['native_run_ids'].remove(earlier))
    monkeypatch.setattr(env.app,'_start_admitted_turn',lambda *a,**k:pytest.fail('Stop must not execute another producer'))
    async def no_external_cancel(*args,**kwargs):
        pytest.fail('This owned synthetic graph must not invoke native MCP')
    monkeypatch.setattr(env.app,'_request_native_cancel',no_external_cancel)
    await env.app.task_owner.cancel(env.tid)
    task=env.app.task_owner.store.get_task(env.tid)
    pending=[asdict(x) for x in SqliteEffectLedger().list(status='pending')]
    (env.artifact.parent/'stop-observation.json').write_text(json.dumps({'fault':fault,'truncate':truncate,
        'task_state':task.state.value,'cancellation':task.cancellation,'pending_effects':pending,
        'cancellation_children':task.payload.get('cancellation_children'),'producer_calls':env.runtime.calls},indent=2)+'\n')
    assert env.runtime.calls==calls
    if fault is None:
        assert not pending
        assert task.state.value=='cancelled'
    else:
        assert pending
        assert task.cancellation
        assert task.state.value!='cancelled', 'Stop hid a pending accepted or qualified-child native effect'


@pytest.mark.asyncio
async def test_stop_unadmitted_task_does_not_require_fabricated_native_evidence(env):
    await env.app.task_owner.cancel(env.tid)
    assert env.app.task_owner.store.get_task(env.tid).state.value == 'cancelled'
    assert env.runtime.calls == 0


@pytest.mark.asyncio
async def test_loss_after_legal_native_completion_before_seal_stays_unknown(env, monkeypatch):
    from jaeger_ai.core.tasks import background_receipts
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from dev.tests.jaeger_ai.core.test_background_terminal_journal import journal, restart
    from dev.tests.jaeger_ai.core.test_owner_request_journal import Crash
    original = background_receipts.complete_native_runs
    def lose(owner, task, roots):
        original(owner, task, roots)
        raise Crash()
    monkeypatch.setattr(background_receipts, 'complete_native_runs', lose)
    with pytest.raises(Crash):
        await env.app.task_owner._execute(env.tid)
    assert journal(env)['terminal_json'] is None
    native = env.store.get_request(env.rid)['native_run_id']
    assert SqliteRunStore().get(native).state == 'completed'
    for _ in range(2):
        app = restart(env)
        assert app._recover_sealed_owner_results() == 0
        assert app.store.get_request(env.rid)['status'] == 'execution_unknown'
    assert env.runtime.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['effect', 'checkpoint', 'child', 'artifact', 'lease', 'cancel'])
async def test_native_completion_is_not_seal_authority_after_drift(env, monkeypatch, fault):
    from jaeger_ai.core.tasks import background_receipts
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from dev.tests.jaeger_ai.core.test_background_terminal_journal import journal
    from dev.tests.jaeger_ai.core.test_background_native_tree_receipts import child
    original = background_receipts.complete_native_runs
    def settle_then_change(owner, task, roots):
        result = original(owner, task, roots)
        if fault == 'effect': pending_effect(roots[0])
        elif fault == 'checkpoint': SqliteRunStore().checkpoint(roots[0], {'changed': True})
        elif fault == 'child': child(roots[0], 'pending')
        elif fault == 'artifact': env.artifact.write_text('SUBSTITUTED')
        elif fault == 'cancel': owner.gateway._cancellations.cancel(env.rid)
        else: owner.gateway._owner_receipt_lease = {**owner.gateway._owner_receipt_lease, 'started_at': -1}
        return result
    monkeypatch.setattr(background_receipts, 'complete_native_runs', settle_then_change)
    await env.app.task_owner._execute(env.tid)
    assert journal(env)['terminal_json'] is None
    assert env.app.task_owner.store.get_task(env.tid).state.value != 'completed_verified'
    assert env.runtime.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['waiting_for_approval', 'failed', 'blocked'])
async def test_incompatible_native_state_before_producer_settlement_is_not_forced(env, state):
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from dev.tests.jaeger_ai.core.test_background_terminal_journal import journal
    produce = env.runtime.before_answer
    def incompatible(native):
        produce(native)
        SqliteRunStore().transition(native, state, wake_key='approval' if state == 'waiting_for_approval' else None)
    env.runtime.before_answer = incompatible
    await env.app.task_owner._execute(env.tid)
    native = env.store.get_request(env.rid)['native_run_id']
    assert SqliteRunStore().get(native).state == state
    assert journal(env)['terminal_json'] is None
    assert env.app.task_owner.store.get_task(env.tid).state.value == 'paused'
