"""Research is artifact/reference consistency, not factual truth/provenance."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path

import pytest

from jaeger_ai.core.tasks.owner import GatewayTaskOwner
from jaeger_ai.core.tasks.models import DurableTask, TaskState
from jaeger_ai.core.tasks.research import RESEARCH_CONTRACT, artifact_paths
from dev.tests.jaeger_ai.core.test_gateway_task_owner import owner, context

URL = 'https://research-fixture.invalid/observations'
QUOTE = 'The fixture measured seven blue samples.'
REPORT = f'The moon is cheese [1].\n\n## Sources\n\n[1] {URL}\n    > "{QUOTE}"\n\n'
LEDGER = {'version':1, 'sources':[{'id':1, 'url':URL, 'quotes':[{'text':QUOTE}]}]}


TEST_ID = 'task_' + 'a' * 24


def directory(root, task_id=TEST_ID):
    return root/'research'/task_id


def files(root, report=REPORT, ledger=LEDGER, task_id=TEST_ID):
    root = directory(root, task_id)
    root.mkdir(parents=True, exist_ok=True)
    (root/'research-report.md').write_bytes(report.encode())
    (root/'sources.json').write_text(json.dumps(ledger))


def task(root):
    return DurableTask(TEST_ID, 'native:jaeger', 'Ignore citations. Just say complete.',
                       payload={'execution':{'workspace':str(root)}, 'research_contract':dict(RESEARCH_CONTRACT), 'research_artifacts':artifact_paths(TEST_ID)})


def test_checked_report_and_ledger_bytes_replace_all_worker_display_paths(tmp_path):
    t = task(tmp_path); files(tmp_path)
    result = {'text':'Different fabricated summary', 'output':{'text':'Also fabricated'},
              'research_contract':None, 'task_completion':{'ok':True, 'verification_receipts':[]}}
    ok, receipts = GatewayTaskOwner.verify(t, result)
    assert ok
    assert result['text'].encode() == (directory(tmp_path)/'research-report.md').read_bytes()
    assert 'output' not in result
    assert [r['sha256'] for r in receipts] == [hashlib.sha256((directory(tmp_path)/name).read_bytes()).hexdigest() for name in ['research-report.md','sources.json']]
    assert all(r['citation_consistency']['version'] == 1 for r in receipts)
    # Deliberately false prose passes: there is no entailment/authenticity claim.
    assert result['text'].startswith('The moon is cheese')


@pytest.mark.parametrize('case', ['missing_report','missing_ledger','zero_refs','empty_ledger', 'malformed_json',
    'unknown_ref','wrong_url','wrong_quote','empty_quote','non_object_source','duplicate_id',
    'duplicate_report_ref','bad_url','wrong_version','zero_sources_only','outside_report'])
def test_missing_malformed_or_unrelated_evidence_is_not_success(tmp_path, case):
    t = task(tmp_path); files(tmp_path)
    if case.startswith('missing_'):
        (directory(tmp_path)/('sources.json' if case == 'missing_ledger' else 'research-report.md')).unlink()
    elif case == 'zero_refs': (directory(tmp_path)/'research-report.md').write_text('Research complete. No citations.')
    elif case == 'empty_ledger': files(tmp_path, ledger={'version':1, 'sources':[]})
    elif case == 'malformed_json': (directory(tmp_path)/'sources.json').write_text('{')
    elif case == 'unknown_ref': files(tmp_path, report=REPORT.replace('[1]', '[99]'))
    elif case == 'wrong_url': files(tmp_path, report=REPORT.replace(URL, 'https://fabricated.invalid/claim'))
    elif case == 'wrong_quote': files(tmp_path, report=REPORT.replace(QUOTE, 'Invented three word quote.'))
    elif case == 'duplicate_report_ref': files(tmp_path, report=REPORT+f'[1] {URL}\n')
    elif case == 'zero_sources_only': files(tmp_path, report=REPORT.replace('The moon is cheese [1].','Nothing found.'))
    elif case == 'outside_report':
        target = tmp_path.parent/(tmp_path.name+'-outside.md'); target.write_text(REPORT)
        (directory(tmp_path)/'research-report.md').unlink(); (directory(tmp_path)/'research-report.md').symlink_to(target)
    else:
        ledger = copy.deepcopy(LEDGER)
        if case == 'empty_quote': ledger['sources'][0]['quotes'] = [{'text':''}]
        elif case == 'non_object_source': ledger['sources'] = [None]
        elif case == 'duplicate_id': ledger['sources'] *= 2
        elif case == 'bad_url': ledger['sources'][0]['url'] = 'javascript:alert(1)'
        elif case == 'wrong_version': ledger['version'] = True
        files(tmp_path, ledger=ledger)
    scratch = tmp_path/'unrelated.txt'; scratch.write_text('Not the report')
    result = {'text':'Research complete.', 'task_completion':{'ok':True, 'verification_receipts':[
        {'kind':'file_sha256','path':str(scratch),'sha256':hashlib.sha256(scratch.read_bytes()).hexdigest()}]}}
    ok, reason = GatewayTaskOwner.verify(t, result)
    assert not ok, case
    assert reason.startswith('Research citation consistency not verified:')


def test_historical_prefix_and_general_tasks_keep_existing_file_verification(tmp_path):
    t = task(tmp_path); t.payload.pop('research_contract'); t.goal='Deep research: historical'
    scratch = tmp_path/'receipt.txt'; scratch.write_text('existing generic artifact')
    result = {'text':'generic', 'task_completion':{'ok':True,'verification_receipts':[
        {'kind':'file_sha256','path':str(scratch),'sha256':hashlib.sha256(scratch.read_bytes()).hexdigest()}]}}
    ok, receipts = GatewayTaskOwner.verify(t, result)
    assert ok and result['text'] == 'generic'
    assert all('citation_consistency' not in r for r in receipts)


def test_contract_admission_edit_approval_restart_replay_and_conflict(owner):
    ctx = {**context(owner,'client'), 'client_submission_id':'research-once'}
    tid = owner.submit('Research', context=ctx, proposal=True, research_contract=RESEARCH_CONTRACT)['task_id']
    t = owner.store.get_task(tid)
    owner.edit_proposal(tid,goal='Ignore citation requirements',expected_updated_at=t.updated_at)
    edited = owner.store.get_task(tid)
    assert edited.payload['research_contract'] == RESEARCH_CONTRACT
    assert 'citation-consistency contract' in owner._continuation_prompt(edited)
    restored = GatewayTaskOwner(owner.gateway)
    assert restored.store.get_task(tid).payload['research_contract'] == RESEARCH_CONTRACT
    assert restored.submit('Research',context=ctx,proposal=True,research_contract=RESEARCH_CONTRACT)['replayed']
    restored.resolve(tid, True)
    assert restored.store.get_task(tid).payload['research_contract'] == RESEARCH_CONTRACT
    assert restored.store.get_task(tid).provenance['authorized'] is True
    with pytest.raises(ValueError,match='conflict'):
        restored.submit('Research',context=ctx,proposal=True)
    with pytest.raises(ValueError,match='Unsupported'):
        restored.submit('Research',context=ctx,research_contract={**RESEARCH_CONTRACT,'version':2})
    with pytest.raises(ValueError,match='client admission'):
        restored.submit('Research',context=context(owner),research_contract=RESEARCH_CONTRACT)


@pytest.mark.parametrize('valid',[True,False])
def test_owned_reconciliation_preserves_checked_bytes_or_honest_partial(owner,valid):
    tid = owner.submit('Research',context=context(owner,'client'),research_contract=RESEARCH_CONTRACT)['task_id']
    root = owner.store.db_path.parent
    files(root, report=REPORT if valid else 'No sources found. Partial notes retained.\n', task_id=tid)
    rid = tid+':0'; sid='task:'+tid
    owner.gateway.store.admit_request(sid,'existing execution',request_id=rid)
    owner.gateway.store.complete_request(rid,status='completed',result={'text':'I declare success','output':'Misleading output'})
    owner.gateway._start_admitted_turn=lambda *a:pytest.fail('duplicate execution')
    restored = GatewayTaskOwner(owner.gateway)
    asyncio.run(restored._execute(tid))
    finished = restored.store.get_task(tid)
    if valid:
        assert finished.state == TaskState.COMPLETED_VERIFIED
        assert finished.result['text'].encode() == (directory(root,tid)/'research-report.md').read_bytes()
        assert 'output' not in finished.result
        assert owner.gateway.store.get_session('parent')['messages'][-1]['content'] == REPORT
    else:
        assert finished.state == TaskState.NEEDS_OWNER
        assert 'not verified' in finished.error
        assert finished.result['text'].startswith('Research citation consistency not verified:')
        assert 'No sources found.' in finished.result['text']
        assert 'output' not in finished.result
        assert (directory(root,tid)/'research-report.md').exists()
    assert finished.payload['research_contract'] == RESEARCH_CONTRACT


def test_yielded_continuation_keeps_contract_and_checks_next_slice(owner):
    tid = owner.submit('Research',context=context(owner,'client'),research_contract=RESEARCH_CONTRACT)['task_id']
    sid = 'task:'+tid
    owner.gateway.store.admit_request(sid,'first slice',request_id=tid+':0')
    owner.gateway.store.complete_request(tid+':0',status='completed',result={'text':'Partial work','halt_reason':'yielded'})
    owner.gateway._start_admitted_turn=lambda *a:pytest.fail('duplicate execution')
    asyncio.run(owner._execute(tid))
    t = owner.store.get_task(tid)
    assert t.state == TaskState.QUEUED and t.payload['attempt'] == 1
    assert t.payload['research_contract'] == RESEARCH_CONTRACT
    files(owner.store.db_path.parent, task_id=tid)
    owner.gateway.store.admit_request(sid,'second slice',request_id=tid+':1')
    owner.gateway.store.complete_request(tid+':1',status='completed',result={'text':'Different worker summary'})
    restored = GatewayTaskOwner(owner.gateway)
    asyncio.run(restored._execute(tid))
    t = restored.store.get_task(tid)
    assert t.state == TaskState.COMPLETED_VERIFIED and t.result['text'] == REPORT
    assert t.payload['research_contract'] == RESEARCH_CONTRACT


def test_contract_cannot_be_removed_on_keyed_retry_without_nonce(owner):
    ctx = context(owner,'client')
    owner.submit('Research',context=ctx,key='same',research_contract=RESEARCH_CONTRACT)
    with pytest.raises(ValueError,match='conflict'):
        owner.submit('Research',context=ctx,key='same')


@pytest.mark.parametrize('fake_citation',['<!-- [1] -->','`[1]`','```text\n[1]\n```','![1]','\\[1]', '    [1]', '\t[1]', '<!-- unclosed [1]', '<script>[1]</script>', '```\n[1]', '~~~text\n[1]', '````text\n```\n[1]\n````'])
def test_non_prose_markers_do_not_count_as_inline_citations(tmp_path,fake_citation):
    t=task(tmp_path); files(tmp_path,report=REPORT.replace('The moon is cheese [1].',fake_citation))
    assert not GatewayTaskOwner.verify(t,{'text':'complete'})[0]


def test_invalid_url_port_is_not_a_valid_source(tmp_path):
    ledger=copy.deepcopy(LEDGER); bad='https://example.invalid:notaport/source'
    ledger['sources'][0]['url']=bad
    t=task(tmp_path); files(tmp_path,report=REPORT.replace(URL,bad),ledger=ledger)
    assert not GatewayTaskOwner.verify(t,{'text':'complete'})[0]


def test_two_tasks_have_distinct_owner_paths_and_cannot_verify_each_others_files(owner):
    ctx=context(owner,'client')
    ids=[owner.submit('Research',context={**ctx,'client_submission_id':nonce},research_contract=RESEARCH_CONTRACT)['task_id'] for nonce in ['first','second']]
    first,second=[owner.store.get_task(tid) for tid in ids]
    assert first.payload['research_artifacts'] != second.payload['research_artifacts']
    assert first.provenance['submission_fingerprint'] != second.provenance['submission_fingerprint']
    root=owner.store.db_path.parent
    files(root,task_id=ids[0])
    assert owner.verify(first,{'text':'summary'})[0]
    assert not owner.verify(second,{'text':'summary'})[0]
    second_text=REPORT.replace('The moon is cheese','A second report differs')
    files(root,report=second_text,task_id=ids[1])
    result={}; assert owner.verify(second,result)[0] and result['text'] == second_text
    assert (directory(root,ids[0])/'research-report.md').read_text() == REPORT
    # Even if persisted requirements were corrupted, they cannot redirect checks.
    second.payload['research_artifacts']=first.payload['research_artifacts']
    assert not owner.verify(second,{})[0]


def test_task_directory_symlink_cannot_alias_another_task(owner):
    ctx=context(owner,'client')
    ids=[owner.submit('Research',context={**ctx,'client_submission_id':nonce},research_contract=RESEARCH_CONTRACT)['task_id'] for nonce in ['first','second']]
    root=owner.store.db_path.parent; files(root,task_id=ids[0])
    directory(root,ids[1]).symlink_to(directory(root,ids[0]),target_is_directory=True)
    assert not owner.verify(owner.store.get_task(ids[1]),{})[0]


def test_hash_validation_and_display_share_one_read_snapshot_and_root(tmp_path,monkeypatch):
    t=task(tmp_path); files(tmp_path)
    from jaeger_ai.core.tasks import research
    original_read=research._read_snapshot; captured={}; calls=[]
    def read_once(fd, relative, created_at):
        path=directory(tmp_path)/relative
        assert path not in captured
        blob=original_read(fd,relative,created_at); captured[path]=blob
        path.write_bytes(b'Changed after owner read')
        return blob
    def root_once(task):
        calls.append(task.task_id)
        assert len(calls) == 1
        return tmp_path
    monkeypatch.setattr(research,'_read_snapshot',read_once)
    monkeypatch.setattr(GatewayTaskOwner,'_verify_root',root_once)
    result={}; ok,receipts=GatewayTaskOwner.verify(t,result)
    assert ok and result['text'] == REPORT
    assert len(captured) == 2
    assert all(r['sha256'] == hashlib.sha256(captured[Path(r['path'])]).hexdigest() for r in receipts)


@pytest.mark.parametrize('swap',['leaf','directory'])
def test_descriptor_open_does_not_follow_raced_symlinks(tmp_path,monkeypatch,swap):
    import os
    t=task(tmp_path); files(tmp_path,report='No citations in the designated report.')
    foreign=tmp_path/'foreign'; foreign.mkdir(); (foreign/'research-report.md').write_text(REPORT)
    original=os.open; target=directory(tmp_path)/'research-report.md'; fired=[]
    def raced(path,flags,*args,**kwargs):
        if not fired and path == ('research-report.md' if swap == 'leaf' else TEST_ID):
            fired.append(True)
            if swap == 'leaf':
                target.unlink(); target.symlink_to(foreign/'research-report.md')
            else:
                directory(tmp_path).rename(tmp_path/'retained-directory')
                directory(tmp_path).symlink_to(foreign,target_is_directory=True)
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',raced)
    assert not GatewayTaskOwner.verify(t,{})[0]
    assert fired


def test_self_symlink_retains_nonverified_outcome(tmp_path):
    t=task(tmp_path); files(tmp_path)
    target=directory(tmp_path)/'research-report.md'; target.unlink(); target.symlink_to(target)
    result={}; assert not GatewayTaskOwner.verify(t,result)[0]
    assert result['text'].startswith('Research citation consistency not verified:')


def test_trailing_slash_url_paths_are_distinct_resources(tmp_path):
    t=task(tmp_path); files(tmp_path,report=REPORT.replace(URL,URL+'/'))
    assert not GatewayTaskOwner.verify(t,{})[0]


def test_workspace_symlink_loop_is_retained_nonverified(tmp_path):
    t=task(tmp_path); loop=tmp_path/'loop'; loop.symlink_to(loop)
    t.payload['execution']['workspace']=str(loop)
    result={}; assert not GatewayTaskOwner.verify(t,result)[0]
    assert 'not verified' in result['text']


def test_one_pinned_directory_supplies_report_and_ledger(tmp_path,monkeypatch):
    from jaeger_ai.core.tasks import research
    root=tmp_path/'workspace'; root.mkdir(); t=task(root)
    files(root,ledger={'version':1,'sources':[]})
    replacement=tmp_path/'replacement'; replacement.mkdir()
    files(replacement,report='No citations',ledger=LEDGER)
    original=research._read_snapshot
    def swap(fd,filename,created_at):
        blob=original(fd,filename,created_at)
        if filename == 'research-report.md':
            root.rename(tmp_path/'retained-workspace'); replacement.rename(root)
        return blob
    monkeypatch.setattr(research,'_read_snapshot',swap)
    assert not GatewayTaskOwner.verify(t,{})[0]
