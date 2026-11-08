"""Controller halt truth through real Gateway persistence, cards and events."""
import pytest
from dev.tests.jaeger_ai.core.test_gateway_turn_card import env, _run, _evidence_for, _states, _events, REQUEST

HALTS = ['context_overflow', 'stalled', 'empty_response', 'thinking_exhausted',
         'interrupted', 'error: RuntimeError', 'future_unknown_halt']

@pytest.mark.asyncio
@pytest.mark.parametrize('halt', HALTS)
@pytest.mark.parametrize('card', [False, True])
async def test_controller_halt_is_not_success(env, halt, card):
    calls = []
    def worker(prompt, **kw):
        calls.append(prompt)
        if card:
            path = env.workspace / 'partial.md'
            path.write_text('incomplete first step')
            return {**_evidence_for(path), 'halt_reason': halt}
        return {'text': '', 'halt_reason': halt}
    row = await _run(env, REQUEST if card else 'hello', 'r-halt', worker=worker)
    assert len(calls) == 1
    assert row['status'] == row['result']['status'] == 'failed'
    assert row['result']['halt_reason'] == row['result']['error'] == halt
    assert env.runtime.finished == []
    assert _states(env)[-1] == 'failed'
    assert [e.event for e in _events(env, 'turn.finish', 'turn.failed')] == ['turn.failed']
    tasks = env.app.task_owner.store.list_tasks()
    assert len(tasks) == int(card)
    if card:
        assert row['result']['task_state'] == 'failed'
        assert row['result']['receipt']['verification'] == 'unverified'
        assert tasks[0].state.value == 'failed'
        assert not any(c[1] == 'completed_verified' for c in env.runtime.claims)

@pytest.mark.asyncio
@pytest.mark.parametrize('halt', ['blocked', 'needs_owner'])
async def test_owner_decision_stays_distinct(env, halt):
    def worker(prompt, **kw):
        path = env.workspace / 'partial.md'
        path.write_text('incomplete first step')
        return {**_evidence_for(path), 'halt_reason': halt}
    row = await _run(env, REQUEST, 'r-decision', worker=worker)
    assert row['status'] == 'completed'
    assert row['result']['task_state'] == halt
    assert row['result']['receipt']['verification'] == 'unverified'
    assert _states(env)[-1] == halt
    assert [e.event for e in _events(env,'turn.finish','turn.failed')] == ['turn.finish']

@pytest.mark.asyncio
async def test_yielded_slice_retains_completed_transport_without_verified_card(env):
    row = await _run(env, REQUEST, 'r-yield', worker=lambda *a, **k: {
        'text': 'Checkpoint retained', 'halt_reason': 'yielded'})
    assert row['status'] == 'completed'
    assert row['result']['halt_reason'] == 'yielded'
    assert row['result']['task_state'] == 'failed'
    assert row['result']['receipt']['verification'] == 'unverified'
    assert [e.event for e in _events(env, 'turn.finish', 'turn.failed')] == ['turn.finish']

@pytest.mark.asyncio
@pytest.mark.parametrize('card', [False, True])
async def test_real_continuation_controller_preserves_failed_halt(env, card):
    continued = env.app._continued_owner_react
    calls = []
    def step(prompt, **kw):
        calls.append(prompt)
        return {'text': 'Stopped mid-task', 'halt_reason': 'context_overflow'}
    env.app._owner_react_turn = step
    row = await _run(env, REQUEST if card else 'hello', 'r-controller', worker=continued)
    assert len(calls) == 1
    assert row['status'] == 'failed'
    assert row['result']['output'] == 'Stopped mid-task'
    assert row['result']['halt_reason'] == 'context_overflow'
    assert env.runtime.finished == []
    assert _states(env)[-1] == 'failed'
    assert [e.event for e in _events(env, 'turn.finish', 'turn.failed')] == ['turn.failed']


@pytest.mark.asyncio
async def test_real_inner_cap_yields_without_verifying_foreground_card(env):
    continued = env.app._continued_owner_react
    calls = []
    def step(prompt, **kw):
        calls.append(prompt)
        return {'text': 'Partial checkpoint',
                'halt_reason': 'hit max_iterations=8 without a final answer'}
    env.app._owner_react_turn = step
    row = await _run(env, REQUEST, 'r-cap', worker=continued)
    # Existing turn-owned budget: initial call plus four continuations.
    assert len(calls) == 5
    assert row['status'] == 'completed'
    assert row['result']['halt_reason'] == 'yielded'
    assert row['result']['output'] == 'Partial checkpoint'
    assert row['result']['task_state'] == 'failed'
    assert row['result']['receipt']['verification'] == 'unverified'
    assert _states(env)[-1] == 'failed'
    assert len(env.app.task_owner.store.list_tasks()) == 1
    assert [e.event for e in _events(env, 'turn.finish', 'turn.failed')] == ['turn.finish']
