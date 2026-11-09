import asyncio
import json
from types import SimpleNamespace
import pytest
from jaeger_ai.core.gateway.chat_organization import ChatOrganization, OrganizationConflict
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.server import JaegerGatewayApp

@pytest.fixture
def organizer(tmp_path):
    store=GatewaySessionStore(tmp_path/'sessions.sqlite3')
    store.ensure_session('a',title='First',workspace='/original/root',metadata={'model':'grok','project_id':'execution-project','permissions':{'write':False}})
    store.ensure_session('b',title='Second')
    return ChatOrganization(store)

def test_atomic_grouping_preserves_execution_and_reopens(organizer):
    before=organizer.store.get_session('a')
    organizer.apply(0,[{'type':'create_group','id':'research','name':'Research','kind':'project'},
        {'type':'move','session_ids':['a'],'field':'project_id','group_id':'research'},
        {'type':'rename','session_ids':['a'],'title':'Research plan'},
        {'type':'pin','session_ids':['a'],'value':True}], 'op')
    after=organizer.store.get_session('a')
    assert after['workspace']==before['workspace']
    assert after['updated_at']==before['updated_at']
    for field in ('model','project_id','permissions'): assert after['metadata'][field]==before['metadata'][field]
    assert after['metadata']['chat_organization']['project_id']=='research'
    reopened=ChatOrganization(GatewaySessionStore(organizer.store.path)).snapshot()
    assert reopened['revision']==1 and reopened['groups'][0]['name']=='Research'
    assert next(s for s in reopened['sessions'] if s['session_id']=='a')['pinned']

def test_invalid_batch_rolls_back_every_change(organizer):
    with pytest.raises(ValueError):
        organizer.apply(0,[{'type':'rename','session_ids':['a'],'title':'Oops'},{'type':'move','session_ids':['b'],'field':'project_id','group_id':'missing'}],'bad')
    assert organizer.snapshot()['revision']==0
    assert organizer.store.get_session('a')['title']=='First'

def test_conflicts_and_idempotent_retry(organizer):
    actions=[{'type':'pin','session_ids':['a'],'value':True}]
    organizer.apply(0,actions,'pin')
    assert organizer.apply(0,actions,'pin')['replayed']
    with pytest.raises(OrganizationConflict):organizer.apply(0,actions,'stale')

def test_undo_does_not_touch_new_chat_or_runtime_metadata(organizer):
    organizer.apply(0,[{'type':'rename','session_ids':['a'],'title':'Changed'},{'type':'archive','session_ids':['a'],'value':True}],'rename')
    organizer.store.ensure_session('new',title='New')
    organizer.store.update_metadata('a',{'runtime_extra':'preserve'})
    organizer.undo('rename')
    assert organizer.store.get_session('a')['title']=='First'
    assert organizer.store.get_session('a')['metadata']['runtime_extra']=='preserve'
    assert organizer.store.get_session('new')['title']=='New'
    assert not organizer.store.get_session('a')['archived']

def test_undo_refuses_to_overwrite_subsequent_edit(organizer):
    organizer.apply(0,[{'type':'rename','session_ids':['a'],'title':'Changed'}],'first')
    organizer.apply(1,[{'type':'rename','session_ids':['a'],'title':'Newer'}],'second')
    with pytest.raises(OrganizationConflict):organizer.undo('first')
    assert organizer.store.get_session('a')['title']=='Newer'

def test_remove_group_retains_chats_and_undo_restores_membership(organizer):
    organizer.apply(0,[{'type':'create_group','id':'s','name':'Work','kind':'section'},
        {'type':'move','session_ids':['a','b'],'field':'section_id','group_id':'s'}],'group')
    organizer.apply(1,[{'type':'remove_group','id':'s'}],'remove')
    assert len(organizer.snapshot()['sessions'])==2
    assert not organizer.snapshot()['groups']
    organizer.undo('remove')
    assert organizer.snapshot()['groups'][0]['name']=='Work'

def test_proposal_never_applies_until_owner_chooses(organizer):
    proposal=organizer.propose([{'type':'rename','session_ids':['a'],'title':'Suggested'}])
    assert organizer.store.get_session('a')['title']=='First'
    assert organizer.snapshot()['proposals'][0]['id']==proposal['id']
    organizer.apply(proposal['revision'],proposal['actions'],'apply')
    assert organizer.store.get_session('a')['title']=='Suggested'

class Request(dict):
    method='POST'
    def __init__(self,name,body=None):
        super().__init__(caller=SimpleNamespace(name=name,session_prefix=None),caller_actor='owner:'+name if name=='webui' else 'agent:'+name)
        self.body=body
    async def json(self):return self.body

def test_agent_can_propose_but_cannot_apply(organizer):
    gateway=JaegerGatewayApp(store=organizer.store)
    req=Request('jaegerd',{'action':'apply','revision':0,'operation_id':'bad','actions':[{'type':'pin','session_ids':['a'],'value':True}]})
    assert asyncio.run(gateway.handle_chat_organization(req)).status==403
    req.body={'action':'propose','actions':[{'type':'rename','session_ids':['a'],'title':'Proposed'}]}
    assert asyncio.run(gateway.handle_chat_organization(req)).status==200
    assert organizer.store.get_session('a')['title']=='First'
    req=Request('webui',{'action':'apply','revision':0,'operation_id':'ok','actions':[{'type':'pin','session_ids':['a'],'value':True}]})
    assert asyncio.run(gateway.handle_chat_organization(req)).status==200

def test_outside_caller_cannot_read_organization(organizer):
    gateway=JaegerGatewayApp(store=organizer.store)
    req=Request('mcp');req.method='GET'
    assert asyncio.run(gateway.handle_chat_organization(req)).status==403

def test_old_rename_route_invalidates_saved_proposal(organizer):
    proposal=organizer.propose([{'type':'rename','session_ids':['a'],'title':'Suggested'}])
    organizer.store.rename_session('a','Owner title')
    with pytest.raises(OrganizationConflict):
        organizer.apply(proposal['revision'],proposal['actions'],'stale-ai')
    assert organizer.store.get_session('a')['metadata']['chat_organization']['manual_title']

def test_operation_id_cannot_be_reused_for_different_changes(organizer):
    organizer.apply(0,[{'type':'pin','session_ids':['a'],'value':True}],'id')
    with pytest.raises(OrganizationConflict):
        organizer.apply(1,[{'type':'archive','session_ids':['a'],'value':True}],'id')

def test_shared_project_context_requires_owner_and_changes_no_permissions(organizer):
    organizer.apply(0,[{'type':'create_group','id':'p','kind':'project','name':'Website'},
        {'type':'group_notes','id':'p','notes':'Use accessible labels.'},
        {'type':'move','session_ids':['a','b'],'field':'project_id','group_id':'p'}],'project')
    for sid in ('a','b'):
        ref=organizer.context(sid,'owner:webui')
        assert ref and 'accessible labels' in ref.text and ref.owner=='document'
    assert organizer.context('a','mcp') is None

def test_undo_group_creation_refuses_to_orphan_new_members(organizer):
    organizer.apply(0,[{'type':'create_group','id':'p','kind':'project','name':'Project'}],'create')
    organizer.apply(1,[{'type':'move','session_ids':['a'],'field':'project_id','group_id':'p'}],'move')
    with pytest.raises(OrganizationConflict):organizer.undo('create')
    assert organizer.snapshot()['groups'][0]['id']=='p'
