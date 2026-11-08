"""Queue admission freezes the same defaults as ordinary sends; no HTTP/provider."""
import copy
import json
import pytest
from dev.tests.jaeger_ai.core.test_gateway_default_admission import probe, Request, new_session, send

async def queue(probe, sid, **extra):
    response = await probe.app.handle_add_queue(Request({'text':'Queued follow-up', 'request_id':'queued', **extra}, sid))
    assert response.status == 202, response.text
    return json.loads(response.text)

@pytest.mark.asyncio
async def test_queue_next_freezes_supported_defaults(probe):
    sid = await new_session(probe)
    await send(probe, sid)  # real normal turn holds session busy
    await queue(probe, sid)
    row = probe.app.store.get_request('queued')
    assert row['status'] == 'queued'
    execution = row['execution']
    assert (execution['model'], execution['provider'], execution['workspace']) == ('gpt-4.1','openai',str(probe.layout.workspace_dir.resolve()))

@pytest.mark.asyncio
async def test_promoted_queue_has_safe_foreground_resume_owner(probe):
    sid = await new_session(probe)
    await send(probe, sid)
    await queue(probe, sid)
    probe.app.store.complete_request('r', status='completed', result={'output':'done'})
    promoted = probe.app.store.promote_next_queue_item(sid)
    assert promoted['request_id'] == 'queued'
    task = probe.app.task_owner.open_turn(session_id=sid, request_id='queued', text='Queued follow-up',strategy='react', owner='owner', execution=promoted['execution'])
    assert task.payload.get('foreground_resume_version') == 1, task.to_dict()

@pytest.mark.asyncio
@pytest.mark.parametrize('explicit',[False,True])
@pytest.mark.parametrize('grant',[None,[],['read_file']])
async def test_explicit_session_caller_grant_replay_controls(probe, monkeypatch, tmp_path, explicit, grant):
    import jaeger_ai.core.gateway.server as server
    monkeypatch.setattr(server,'current_request_actor',lambda: 'owner-test')
    project = tmp_path/'project'; project.mkdir()
    sid = await new_session(probe, workspace=str(project),metadata={'model':'session-model','provider':'openai'})
    await send(probe,sid)
    choices = {'allowed_tools':grant,'caller':'forged'}
    if explicit: choices.update(model='explicit-model',provider='openai',workspace=str(tmp_path/'explicit'))
    await queue(probe,sid,**choices)
    original = copy.deepcopy(probe.app.store.get_request('queued')['execution'])
    assert original['model'] == ('explicit-model' if explicit else 'session-model')
    assert original['workspace'] == (str(tmp_path/'explicit') if explicit else str(project))
    assert original['allowed_tools'] == grant and original['caller'] == 'owner-test'
    probe.config.external_model.model = 'changed-global'
    probe.layout.workspace_dir = tmp_path/'changed-global-workspace'
    probe.app.store.update_metadata(sid,{'model':'changed-session','provider':'anthropic'})
    def forbidden(): pytest.fail('Replay must not read new instance defaults')
    monkeypatch.setattr(probe.app,'_foreground_execution_defaults',forbidden)
    receipt = await queue(probe,sid,**choices)
    assert receipt['replayed'] is True
    assert probe.app.store.get_request('queued')['execution'] == original
    probe.app.store.complete_request('r',status='completed',result={'output':'done'})
    promoted = probe.app.store.promote_next_queue_item(sid)
    assert promoted['execution'] == original
    # Implicit snapshot does not overwrite newly selected conversation model.
    if not explicit: assert probe.app.store.get_session(sid)['metadata']['model'] == 'changed-session'

@pytest.mark.asyncio
async def test_promoted_queue_rejects_changed_default_workspace(probe):
    from jaeger_ai.core.runtime.execution_defaults import execution_project_root
    sid = await new_session(probe)
    await send(probe,sid)
    await queue(probe,sid)
    probe.layout.workspace_dir = probe.layout.root/'later-global-workspace'
    probe.app.store.complete_request('r',status='completed',result={'output':'done'})
    promoted = probe.app.store.promote_next_queue_item(sid)
    with pytest.raises(ValueError,match='no tool dispatch'):
        execution_project_root(promoted['execution'],probe.layout)

@pytest.mark.asyncio
async def test_default_queue_replay_promotion_never_refreshes_defaults(probe, monkeypatch):
    from jaeger_ai.core.runtime.execution_defaults import execution_project_root, validate_default_route
    sid = await new_session(probe)
    await send(probe, sid)
    await queue(probe, sid, allowed_tools=[])
    original = copy.deepcopy(probe.app.store.get_request('queued'))
    execution = original['execution']
    assert execution['_instance_defaults']['workspace'] == execution['workspace']
    assert execution_project_root(execution, probe.layout) is None
    before_session = copy.deepcopy(probe.app.store.get_session(sid))
    probe.config.external_model.model = 'later-global'
    def forbidden(): pytest.fail('Existing request must not rediscover defaults')
    monkeypatch.setattr(probe.app, '_foreground_execution_defaults', forbidden)
    replay = await queue(probe, sid, allowed_tools=[])
    assert replay['replayed'] is True
    assert probe.app.store.get_session(sid) == before_session
    assert probe.app.store.get_request('queued') == original
    probe.app.store.complete_request('r', status='completed', result={'output':'done'})
    promoted = probe.app.store.promote_next_queue_item(sid)
    assert promoted['execution'] == execution
    with pytest.raises(ValueError, match='no model dispatch'):
        validate_default_route(probe.config, promoted['execution']['_instance_defaults']['route_fingerprint'])

@pytest.mark.asyncio
async def test_legacy_queue_is_not_backfilled_on_replay_or_promotion(probe, monkeypatch):
    sid = await new_session(probe)
    await send(probe, sid)
    original = probe.app.store.enqueue_request(sid, 'Queued follow-up', request_id='queued', requested={'interaction_tier':'agent'})
    assert original['execution']['workspace'] == ''
    def forbidden(): pytest.fail('Historical queue receipt must not discover defaults')
    monkeypatch.setattr(probe.app, '_foreground_execution_defaults', forbidden)
    assert (await queue(probe, sid))['replayed'] is True
    probe.app.store.complete_request('r', status='completed', result={'output':'done'})
    assert probe.app.store.promote_next_queue_item(sid)['execution'] == original['execution']

@pytest.mark.asyncio
async def test_queue_cross_session_replay_rejected_before_defaults(probe, monkeypatch):
    sid = await new_session(probe)
    await send(probe, sid)
    await queue(probe, sid)
    other = await new_session(probe)
    before = copy.deepcopy(probe.app.store.get_session(other))
    def forbidden(): pytest.fail('Conflicting receipt must not discover defaults')
    monkeypatch.setattr(probe.app, '_foreground_execution_defaults', forbidden)
    response = await probe.app.handle_add_queue(Request({'text':'Queued follow-up','request_id':'queued'},other))
    assert response.status == 409
    assert probe.app.store.get_session(other) == before

@pytest.mark.asyncio
async def test_default_queue_grants_and_revision_are_not_synthesized(probe, monkeypatch):
    import jaeger_ai.core.gateway.server as server
    monkeypatch.setattr(server, 'current_request_actor', lambda: 'authenticated-owner')
    sid = await new_session(probe)
    await send(probe, sid)
    before = copy.deepcopy(probe.app.store.get_session(sid)['metadata'])
    await queue(probe, sid, allowed_tools=[], caller='forged', _instance_defaults={'workspace':'/forged'})
    execution = probe.app.store.get_request('queued')['execution']
    assert execution['caller'] == 'authenticated-owner'
    assert execution['allowed_tools'] == []
    assert execution['interaction_tier'] == 'agent'
    assert execution['_instance_defaults']['workspace'] == str(probe.layout.workspace_dir)
    assert probe.app.store.get_session(sid)['metadata'] == before
    probe.app.store.complete_request('r',status='completed',result={'output':'done'})
    probe.app.store.promote_next_queue_item(sid)
    assert probe.app.store.get_session(sid)['metadata'] == before
