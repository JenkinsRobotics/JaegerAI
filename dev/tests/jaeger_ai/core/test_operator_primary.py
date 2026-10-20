"""Operator primary is presentation metadata, never an execution identity transfer."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
import pytest
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.agent_presentation import project, PresentationConflict
from jaeger_ai.core.gateway.agent_summary import summarize_agents
from jaeger_ai.core.gateway.caller_auth import required_scope, prefixed_route_allowed


def record(aid, role='specialist', **extra):
    return dict(id=aid, name=aid, kind='jaeger_native', role=role, metadata={'context': 'retained'}, allowed_tools=['read_file'], **extra)


def app_for(store, rows):
    records = {r['id']: SimpleNamespace(id=r['id'], to_dict=lambda r=r: deepcopy(r)) for r in rows}
    return SimpleNamespace(store=store, _registry=lambda: SimpleNamespace(get_agent=records.get), event_bus=SimpleNamespace(publish=lambda *a: None))


def primary(app, aid, expected='native:jaeger'):
    async def body(): return {'agent_id': aid, 'expected_agent_id': expected}
    return asyncio.run(JaegerGatewayApp.handle_agent_primary(app, SimpleNamespace(method='POST', json=body)))


def test_switch_restart_keeps_history_execution_identity_and_previous_primary(tmp_path):
    store = GatewaySessionStore(tmp_path / 'db')
    rows = [record('native:jaeger', 'lead'), record('native:a'), record('native:b')]
    saved = deepcopy(rows)
    for row in rows:
        sid = 'agent-' + row['id']
        store.ensure_session(sid, metadata={'agent_id': row['id'], 'home': True})
        store.append_message(sid, 'user', 'unique context ' + row['id'])
        store.update_status(sid, 'running')
    histories = [store.get_session('agent-' + r['id']) for r in rows]
    app = app_for(store, rows)
    assert store.primary_agent_id() == 'native:jaeger'
    assert primary(app, 'native:a').status == 200
    assert store.agent_presentation()['native:a']['pinned']
    reopened = GatewaySessionStore(store.path)
    assert reopened.primary_agent_id() == 'native:a'
    assert primary(app_for(reopened, rows), 'native:b', 'native:a').status == 200
    views = [project(r, reopened.agent_presentation(), primary_id=reopened.primary_agent_id(), writable=True) for r in rows]
    assert [v['id'] for v in views if v['primary']] == ['native:b']
    assert views[0]['role'] == 'lead' and views[2]['role'] == 'specialist'
    assert rows == saved
    assert [reopened.get_session('agent-' + r['id']) for r in rows] == histories
    # Hiding the primary never silently reassigns it; restore is reversible.
    reopened.patch_agent_presentation('native:b', {'archived': True})
    assert reopened.primary_agent_id() == 'native:b'
    assert primary(app_for(reopened, rows), 'native:b', 'native:b').status == 409
    reopened.patch_agent_presentation('native:b', {'archived': False})
    assert primary(app_for(reopened, rows), 'native:a', 'native:b').status == 200


def test_primary_conflict_full_pins_and_ineligible_are_atomic(tmp_path):
    store = GatewaySessionStore(tmp_path / 'db')
    rows = [record('native:jaeger', 'lead'), record('native:a'), record('native:b'), record('native:internal', metadata_dummy=True)]
    rows[-1]['metadata']['internal'] = True
    rows += [record('native:runtime', 'runtime'), record('tp:x', kind_dummy=True)]
    rows[-1]['kind'] = 'third_party'
    app = app_for(store, rows)
    assert primary(app, 'native:a').status == 200
    before = store.agent_presentation()
    assert primary(app, 'native:b', 'native:jaeger').status == 409
    assert store.agent_presentation() == before
    for aid in ['native:internal', 'native:runtime', 'tp:x']:
        assert primary(app, aid, 'native:a').status == 409
    assert primary(app, 'missing', 'native:a').status == 404
    store.set_agent_pins([f'pin{i}' for i in range(8)], ['native:a'])
    before = store.agent_presentation()
    assert primary(app, 'native:b', 'native:a').status == 409
    assert store.primary_agent_id() == 'native:a' and store.agent_presentation() == before
    with pytest.raises(PresentationConflict): store.set_agent_pins([], ['native:a'])
    for route in ['/v1/agents/primary', '/v1/agents/{id}/seen']:
        assert required_scope('POST', route) == 'admin'
        assert not prefixed_route_allowed('POST', route)


def test_explicit_unread_survives_reload_even_without_activity_and_open_read_clears(tmp_path):
    store = GatewaySessionStore(tmp_path / 'db')
    row = record('native:a')
    def unseen(current, sessions):
        return summarize_agents([row], tasks=[], handoffs=[], sessions=sessions, seen=current.agents_seen())['agents'][0]['unseen']
    store.mark_agent_seen('native:a', seen_at=200)
    sessions = [{'session_id': 'home', 'agent_id': 'native:a', 'updated_at': 100}]
    assert not unseen(store, sessions)
    store.mark_agent_seen('native:a', seen_at=201, unread=True)
    reopened = GatewaySessionStore(store.path)
    assert unseen(reopened, []) and unseen(reopened, sessions)
    reopened.mark_agent_seen('native:a', seen_at=202)
    assert not unseen(store, sessions)
    sessions[0]['updated_at'] = 203
    assert unseen(store, sessions)
