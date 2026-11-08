"""Real specialist setup binds the canonical playbook scope, never a shim."""
import asyncio
import threading

import pytest

from jaeger_agent.skill_registry import playbook_skills as pb
from jaeger_agent.tool_executor import active_caller_identity, active_tool_allowlist
from jaeger_ai.core.agent_registry.specialists import scoped_skill_names
from jaeger_ai.core.agent_registry.types import AgentRecord
from dev.tests.jaeger_ai.core.test_owner_request_journal import env  # noqa: F401


def specialist(name):
    return AgentRecord.from_dict({'id': f'native:{name}', 'name': name,
                                  'kind': 'jaeger_native', 'role': 'specialist'})


@pytest.mark.asyncio
async def test_real_specialist_setup_is_scoped_through_owner_threads(env, monkeypatch):
    agents = {'s': specialist('builder'), 'other': specialist('reviewer')}
    monkeypatch.setattr(env.app, '_resolve_session_agent', agents.get)
    monkeypatch.setattr(env.app, '_auto_route', lambda *a: False)
    rows = [env.row, env.store.admit_request('other', 'hello', request_id='other', requested={
        'model': 'scripted', 'provider': 'scripted', 'caller': 'agent:other',
        'allowed_tools': ['get_time', 'definitely-not-a-specialist-tool'],
    })]
    env.app._cancellations.register('other')
    env.runtime.answers *= 2
    barrier = threading.Barrier(2, timeout=10)
    seen = []
    original_prepare = env.runtime.prepare_turn

    def prepare(text, **kwargs):
        scope = pb.active_skill_scope()
        assert scope == frozenset(scoped_skill_names(agents[kwargs['session_id']]))
        return original_prepare(text, **kwargs)

    def observe(_run):
        actor = active_caller_identity()
        own = 'jaeger-builder' if actor == 'agent:test' else 'jaeger-reviewer'
        denied = 'jaeger-reviewer' if actor == 'agent:test' else 'jaeger-builder'
        scope = pb.active_skill_scope()
        barrier.wait()
        assert pb.active_skill_scope() == scope
        assert own in scope and denied not in scope
        assert pb.find_playbook(denied) is None
        seen.append((actor, active_tool_allowlist(), scope))

    monkeypatch.setattr(env.runtime, 'prepare_turn', prepare)
    env.runtime.before_answer = observe
    # An enclosing scope must be restored, not cleared or leaked after await.
    with pb.skill_scope(['outer-only']):
        await asyncio.gather(*(env.app._execute_turn(
            row['session_id'], row['turn_id'], row['input_text'],
            request_id=row['request_id'], execution=row['execution'],
        ) for row in rows))
        assert pb.active_skill_scope() == frozenset({'outer-only'})
    assert pb.active_skill_scope() is None
    assert len(seen) == 2
    assert dict((actor, tools) for actor, tools, _ in seen) == {
        'agent:test': frozenset(), 'agent:other': frozenset({'get_time'}),
    }
    for row in rows:
        assert env.store.get_request(row['request_id'])['status'] == 'completed'
    assert env.row['execution']['allowed_tools'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [RuntimeError, asyncio.CancelledError])
async def test_specialist_scope_restores_after_setup_failure(env, monkeypatch, failure):
    monkeypatch.setattr(env.app, '_resolve_session_agent', lambda sid: specialist('builder'))
    monkeypatch.setattr(env.app, '_auto_route', lambda *a: False)

    def fail(*a, **kw):
        assert 'jaeger-builder' in pb.active_skill_scope()
        raise failure('controlled setup failure')

    monkeypatch.setattr(env.app.event_bus, 'publish', fail)
    with pb.skill_scope(['outer-only']):
        with pytest.raises(failure):
            await env.app._execute_turn(
                's', env.row['turn_id'], 'hello', request_id='r', execution=env.row['execution'])
        assert pb.active_skill_scope() == frozenset({'outer-only'})
    assert pb.active_skill_scope() is None


@pytest.mark.asyncio
async def test_empty_skill_scope_stays_restrictive(env, monkeypatch):
    from jaeger_ai.core.agent_registry import specialists
    monkeypatch.setattr(env.app, '_resolve_session_agent', lambda sid: specialist('builder'))
    monkeypatch.setattr(env.app, '_auto_route', lambda *a: False)
    monkeypatch.setattr(specialists, 'scoped_skill_names', lambda agent: [])
    seen = []

    def observe(_run):
        seen.append(pb.active_skill_scope())
        assert pb.callable_playbooks() == []
        assert pb.find_playbook('jaeger-builder') is None

    env.runtime.before_answer = observe
    await env.app._execute_turn('s', env.row['turn_id'], 'hello', request_id='r', execution=env.row['execution'])
    assert seen == [frozenset()]
    assert env.store.get_request('r')['status'] == 'completed'
    assert pb.active_skill_scope() is None


@pytest.mark.asyncio
async def test_cancelling_await_restores_scope_without_unscoping_worker(env, monkeypatch):
    monkeypatch.setattr(env.app, '_resolve_session_agent', lambda sid: specialist('builder'))
    monkeypatch.setattr(env.app, '_auto_route', lambda *a: False)
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    observed = []

    def observe(_run):
        entered.set()
        try:
            assert release.wait(10)
            observed.append(pb.active_skill_scope())
        finally:
            returned.set()

    env.runtime.before_answer = observe
    with pb.skill_scope(['outer-only']):
        task = asyncio.create_task(env.app._execute_turn(
            's', env.row['turn_id'], 'hello', request_id='r', execution=env.row['execution']))
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert pb.active_skill_scope() == frozenset({'outer-only'})
        finally:
            release.set()
            assert await asyncio.to_thread(returned.wait, 10)
            assert await asyncio.to_thread(env.runtime.returned.wait, 10)
    assert observed == [frozenset(scoped_skill_names(specialist('builder')))]
    assert pb.active_skill_scope() is None
