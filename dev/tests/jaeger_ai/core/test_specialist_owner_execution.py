"""No-selector HTTP turn autoroutes into the real OWNER without skill shims.

Reuse the isolated OWNER fixture: only model/provider and inventory are scripted;
non-owned sockets are denied, all runtime/skills/authority execution stays real.
"""
import json

import pytest

from jaeger_agent.skill_registry import playbook_skills as pb
from jaeger_agent.tool_executor import active_caller_identity, active_tool_allowlist
from jaeger_ai.core.gateway import caller_auth
from dev.tests.jaeger_ai.core.test_agent_bridge_owner_path import owner_bridge, wait_for  # noqa: F401


@pytest.mark.asyncio
async def test_default_session_autoroutes_to_scoped_real_owner(owner_bridge, monkeypatch):
    client, app, runtime, model, stacks = owner_bridge
    seen = []

    def call(formatted, interrupt_event, **kwargs):
        model.calls += 1
        scope = pb.active_skill_scope()
        assert scope is not None and 'jaeger-builder' not in scope
        assert pb.find_playbook('jaeger-builder') is None
        allowed = active_tool_allowlist()
        assert 'get_time' in allowed and 'write_file' not in allowed
        seen.append((active_caller_identity(), scope))
        if model.calls == 1:
            return {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'denied-write', 'name': 'write_file',
                 'arguments': {'path': 'forbidden.txt', 'content': 'must not be written'}}]}
        results = [json.loads(m['content']) for m in formatted['messages'] if m.get('role') == 'tool']
        assert results and any(r.get('ok') is False or r.get('error') for r in results)
        return {'role': 'assistant', 'content': 'Blocked: requested tool is outside my grant.'}

    monkeypatch.setattr(model, 'call', call)
    headers = caller_auth.client_headers('cli')
    response = await client.post('/v1/sessions', headers=headers, json={})
    assert response.status == 201, await response.text()
    created = await response.json()
    sid = created.get('session_id') or created.get('session', created).get('id')
    assert sid, created
    response = await client.post(f'/v1/sessions/{sid}/turns', headers=headers,
                                 json={'text': 'check my calendar', 'request_id': 'scope-proof'})
    assert response.status in (200, 202), await response.text()
    await wait_for(lambda: app.store.get_request('scope-proof')['status'] in {'completed', 'failed'}, app)
    receipt = app.store.get_request('scope-proof')
    assert receipt['status'] == 'completed', receipt
    assert app.store.get_session(sid)['metadata']['agent_id'] == 'native:everyday'
    assert seen and all(actor == 'owner:cli' for actor, _ in seen), seen
    assert stacks and any('run_subordinate_react' in stack for stack in stacks)
    assert not (runtime.layout.workspace_dir / 'forbidden.txt').exists()
    assert not app.store.list_pending_approvals()
    assert pb.active_skill_scope() is None
