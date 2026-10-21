"""Canonical notes identity, shared locked writer and operator contracts."""
from types import SimpleNamespace
import pytest
from jaeger_ai.core.agent_registry.notes import directory
from jaeger_agent.tools.agent_notes import read_notes,mutate_notes,note_versions,agent_notes,bound_notes_dir


def test_notes_identity_never_shares_colliding_names_or_discards_legacy(tmp_path):
    alpha=SimpleNamespace(id='owned-alpha',name='a'*60+'alpha');beta=SimpleNamespace(id='owned-beta',name='a'*60+'beta')
    a=directory(alpha,tmp_path,[alpha,beta]);b=directory(beta,tmp_path,[alpha,beta]);assert a!=b
    legacy=tmp_path/'memory'/'agents'/('a'*48);legacy.mkdir(parents=True);(legacy/'NOTES.md').write_text('owned legacy')
    with pytest.raises(ValueError,match='ambiguous'):directory(alpha,tmp_path,[alpha,beta])
    assert (legacy/'NOTES.md').read_text()=='owned legacy'
    assert directory(alpha,tmp_path,[alpha])==legacy
    a.mkdir(parents=True);(a/'NOTES.md').write_text('owned newer')
    with pytest.raises(ValueError,match='Both'):directory(alpha,tmp_path,[alpha])
    assert (a/'NOTES.md').read_text()=='owned newer'


def test_tool_and_operator_share_revisions_backups_stale_rejection_and_restore(tmp_path):
    root=tmp_path/'owned-notes';empty=read_notes(root)
    first=mutate_notes(root,'replace','First notes',expected_revision=empty['revision'])
    with bound_notes_dir(root):
        added=agent_notes('append','Second notes',expected_revision=first['revision'])
    assert added['ok'] and 'Second notes' in read_notes(root)['notes']
    with pytest.raises(ValueError,match='changed'):mutate_notes(root,'replace','Stale overwrite',expected_revision=first['revision'])
    assert first['revision'] in {v['revision'] for v in note_versions(root)}
    current=read_notes(root);restored=mutate_notes(root,'restore',expected_revision=current['revision'],restore_revision=first['revision'])
    assert restored['notes']==first['notes']
    assert current['revision'] in {v['revision'] for v in note_versions(root)}
    with pytest.raises(ValueError):mutate_notes(root,'replace','',expected_revision=restored['revision'])
    assert read_notes(root)['notes']==first['notes']


@pytest.mark.asyncio
async def test_http_memory_edits_do_not_change_agent_authority_or_history(tmp_path,monkeypatch):
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config,ModelConfig,dump_yaml
    layout=InstanceLayout(root=tmp_path/'instance');layout.ensure_dirs();dump_yaml(layout.config_path,Config(instance_name='memory-fixture',model=ModelConfig(model_path='/dev/null')))
    monkeypatch.setenv('JAEGER_INSTANCE_DIR',str(layout.root))
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned-history',metadata={'agent_id':'native:builder'});gateway.store.append_message('owned-history','user','Owned existing history')
    original=gateway._registry().get_agent('native:builder').to_dict()
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as client:
        current=await (await client.get('/v1/agents/native:builder/memory')).json()
        assert current['agent_id']=='native:builder' and current['editable']
        body={'operation_id':'owned-memory-save','action':'replace','expected_revision':current['revision'],'text':'Owned preference fixture'}
        response=await client.post('/v1/agents/native:builder/memory',json=body);assert response.status==200
        receipt=await response.json();assert receipt['ok']
        assert await (await client.post('/v1/agents/native:builder/memory',json=body)).json()==receipt
        assert (await client.post('/v1/agents/native:builder/memory',json={**body,'operation_id':'owned-stale-memory','text':'Stale overwrite'})).status==409
        reread=await (await client.get('/v1/agents/native:builder/memory')).json()
        assert reread['notes']=='Owned preference fixture\n' and reread['revision']==receipt['revision']
        assert 'Owned preference fixture' in gateway._system_prompt_for_agent(gateway._registry().get_agent('native:builder'))
        assert gateway._registry().get_agent('native:builder').to_dict()==original
        assert len(gateway.store.get_session('owned-history')['messages'])==1 and gateway.store.list_requests()==[]
        protected=await client.post('/v1/agents/native:gateway/memory',json={**body,'operation_id':'owned-protected-memory'})
        assert protected.status==403
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as client:
        assert (await client.get('/v1/agents/native:builder/memory')).status==403
        assert (await client.post('/v1/agents/native:builder/memory',json=body)).status==403


def test_notes_writer_serializes_concurrent_appends_and_preserves_readonly_mode(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    root=tmp_path/'owned-concurrent'
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda i:mutate_notes(root,'append',f'owned-line-{i}'),range(12)))
    content=read_notes(root)['notes']
    assert sorted(content.splitlines())==sorted(f'owned-line-{i}' for i in range(12))
    file=root/'NOTES.md';file.chmod(0o440);before=file.read_bytes()
    try:
        with pytest.raises(ValueError,match='read-only'):
            mutate_notes(root,'replace','Not authorized to change readonly file')
        assert file.read_bytes()==before and file.stat().st_mode & 0o777==0o440
    finally:file.chmod(0o600)
