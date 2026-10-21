"""Owned verified task receipts → Library/shared safe file reader; no model grants."""
import base64
import hashlib

import pytest

from jaeger_ai.core.tasks.models import TaskState
from jaeger_ai.core.tasks.store import SqliteDurableTaskStore

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


def verified_task(app, root, *, tid='owned-artifact-task', name='result.txt', content=b'Owned result'):
    root.mkdir(exist_ok=True)
    path=root/name;path.write_bytes(content)
    app.store.ensure_session('owned-artifact-origin',workspace=str(root))
    app.task_owner.admit_turn_card({'task_id':tid,'session_id':'owned-artifact-origin','goal':'Owned verified result'},execution={'workspace':str(root)},artifacts=[str(path)])
    task=app.task_owner.store.get_task(tid)
    ok,evidence=app.task_owner.verify(task,{})
    assert ok
    app.task_owner.settle_turn_card(tid,TaskState.COMPLETED_VERIFIED,evidence=evidence,result={'output':str(path)})
    return path


@pytest.mark.asyncio
async def test_verified_reference_reopens_one_identity_after_store_reopen_and_checks_original_bytes(gw,tmp_path):
    app,http=gw;root=tmp_path/'artifacts';path=verified_task(app,root)
    before=app.store.list_messages('owned-artifact-origin')
    first=await (await http.get('/v1/library/artifacts')).json();ref=first['artifacts'][0]
    assert ref['name']=='result.txt' and ref['readable'] and ref['session_id']=='owned-artifact-origin'
    assert 'safe_path' not in ref and str(root) not in str(first)
    app.task_owner.store=SqliteDurableTaskStore(app.store.path)
    repeated=await (await http.get('/v1/library/artifacts?task_id=owned-artifact-task')).json()
    assert repeated==first
    url=f"/v1/library/artifacts/{ref['task_id']}/{ref['attachment_id']}"
    response=await http.get(url);assert response.status==200
    data=await response.json();assert base64.b64decode(data['data_base64'])==b'Owned result'
    assert data['sha256']==hashlib.sha256(b'Owned result').hexdigest()
    path.write_bytes(b'Changed result')
    assert (await http.get(url)).status==409
    assert (await (await http.get('/v1/library/artifacts')).json())['artifacts'][0]['attachment_id']==ref['attachment_id']
    path.unlink()
    missing=(await (await http.get('/v1/library/artifacts')).json())['artifacts'][0]
    assert missing['attachment_id']==ref['attachment_id'] and missing['name']=='result.txt' and not missing['readable']
    assert (await http.get(url)).status==409
    assert app.store.list_messages('owned-artifact-origin')==before
    assert not app.store.list_attachments('owned-artifact-origin')  # no duplicate identity/upload/store


@pytest.mark.asyncio
async def test_model_result_paths_and_unverified_receipts_do_not_become_artifacts(gw,tmp_path):
    app,http=gw;root=tmp_path/'not-verified';root.mkdir();path=root/'claim.txt';path.write_text('Model claim')
    app.store.ensure_session('unverified',workspace=str(root))
    app.task_owner.admit_turn_card({'task_id':'unverified-task','session_id':'unverified','goal':'Model claim'},execution={'workspace':str(root)})
    app.task_owner.store.update_task('unverified-task',lambda t:setattr(t,'result',{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))
    assert not (await (await http.get('/v1/library/artifacts')).json())['artifacts']
    assert (await http.get('/v1/library/artifacts/unverified-task/anything')).status==404


@pytest.mark.asyncio
async def test_current_workspace_scope_and_prefixed_callers_withhold_artifacts(gw,tmp_path):
    from jaeger_ai.core.gateway.caller_auth import client_headers
    app,http=gw;root=tmp_path/'workspace';verified_task(app,root)
    ref=(await (await http.get('/v1/library/artifacts')).json())['artifacts'][0]
    url=f"/v1/library/artifacts/{ref['task_id']}/{ref['attachment_id']}"
    for endpoint in ('/v1/library/artifacts',url):
        assert (await http.get(endpoint,headers=client_headers('a2a'))).status==403
        assert (await http.get(endpoint,headers={'Authorization':'Bearer invalid-owned-test'})).status==401
    # Existing owner revokes/moves the originating session's workspace. No new grant.
    with app.store._immediate() as conn:conn.execute('UPDATE sessions SET workspace=? WHERE session_id=?',(str(tmp_path/'different'),'owned-artifact-origin'))
    refs=(await (await http.get('/v1/library/artifacts')).json())['artifacts']
    assert refs[0]['attachment_id']==ref['attachment_id'] and not refs[0]['readable']
    assert (await http.get(url)).status==409


@pytest.mark.asyncio
async def test_symlink_swap_sensitive_paths_and_foreign_artifact_identity_are_withheld(gw,tmp_path):
    app,http=gw;root=tmp_path/'safe';path=verified_task(app,root)
    ref=(await (await http.get('/v1/library/artifacts')).json())['artifacts'][0]
    url=f"/v1/library/artifacts/{ref['task_id']}/{ref['attachment_id']}"
    foreign=tmp_path/'foreign.txt';foreign.write_bytes(path.read_bytes());path.unlink();path.symlink_to(foreign)
    assert (await http.get(url)).status==409
    refs=(await (await http.get('/v1/library/artifacts')).json())['artifacts']
    assert refs[0]['attachment_id']==ref['attachment_id'] and not refs[0]['readable']
    path.unlink();secret=root/'.env';secret.write_bytes(b'Owned result');path.symlink_to(secret)
    assert (await http.get(url)).status==409
    verified_task(app,root,tid='second-task',name='second.txt')
    assert (await http.get(url.replace('owned-artifact-task','second-task'))).status==404
    verified_task(app,root,tid='secret-task',name='.env',content=b'Dummy fixture, no real credential')
    assert not (await (await http.get('/v1/library/artifacts?task_id=secret-task')).json())['artifacts']


@pytest.mark.asyncio
async def test_artifact_pdf_uses_shared_preview_and_session_filter(gw,tmp_path):
    import shutil
    if not all(shutil.which(n) for n in ('pdfinfo','pdftoppm')):pytest.skip('Existing local parser unavailable; no installation')
    from dev.tests.jaeger_ai.core.test_pdf_preview import owned_pdf
    app,http=gw;verified_task(app,tmp_path/'pdf-artifact',name='result.pdf',content=owned_pdf())
    refs=await (await http.get('/v1/library/artifacts?session_id=owned-artifact-origin')).json()
    ref=refs['artifacts'][0]
    assert not (await (await http.get('/v1/library/artifacts?session_id=other')).json())['artifacts']
    preview=await (await http.get(f"/v1/library/artifacts/{ref['task_id']}/{ref['attachment_id']}?view=preview&page=2")).json()
    assert preview['session_id']=='owned-artifact-origin' and preview['attachment_id']==ref['attachment_id']
    assert preview['sha256']==ref['sha256'] and preview['preview']['page']==2
    assert 'Owned PDF page two' in preview['preview']['text']
