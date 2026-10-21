"""Actual local CLI/metadata read plan, owned fixtures only; never an upgrade."""
import json
import subprocess

import pytest

from jaeger_ai.core.instance import instance
from jaeger_ai.core.instance.schemas import SCHEMA_VERSION

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


@pytest.fixture
def owned_checkout(tmp_path):
    repo=tmp_path/'checkout';repo.mkdir()
    subprocess.run(['git','-C',str(repo),'init','-q'],check=True)
    (repo/'owned.txt').write_text('Owned source')
    subprocess.run(['git','-C',str(repo),'add','owned.txt'],check=True)
    subprocess.run(['git','-C',str(repo),'-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','Owned fixture'],check=True)
    return repo


@pytest.mark.asyncio
async def test_canonical_update_plan_reads_owned_git_and_manifest_without_install_network_or_replay(gw,tmp_path,monkeypatch,owned_checkout):
    app,http=gw;repo=owned_checkout;state=tmp_path/'instance';state.mkdir();(state/'manifest.json').write_text(json.dumps({'schema_version':SCHEMA_VERSION,'private':'NEVER PROJECT'}))
    monkeypatch.setattr(instance,'install_root',lambda:repo);monkeypatch.setattr(instance,'detect_install_method',lambda:'dev-checkout');monkeypatch.setattr(app,'_instance_root',lambda:state)
    app.store.ensure_session('owned-update-unknown');app.store.admit_request('owned-update-unknown','Owned request never dispatched',request_id='owned-update-unknown-request');app.store.mark_request_status('owned-update-unknown-request','execution_unknown')
    before=app.store.get_request('owned-update-unknown-request');manifest=(state/'manifest.json').read_bytes()
    response=await http.get('/v1/runtime/updates/plan?channel=latest');assert response.status==200
    plan=await response.json();assert plan['channel']=='latest' and plan['source_checkout_dirty'] is False
    assert len(plan['source_checkout_revision'])==40 and plan['migration_state']=='current'
    assert plan['check_command']==['jaeger','update','--check','--channel','latest']
    assert plan['release_state']=='not_probed' and plan['signature_state']=='no_verified_candidate'
    assert not plan['automatic_install_supported'] and not plan['automatic_restart_supported']
    assert 'execution_unknown_requires_reconciliation' in plan['restart_blockers']
    assert plan['work']['unknown_requests']==1 and 'NEVER PROJECT' not in str(plan) and str(state) not in str(plan)
    assert app.store.get_request('owned-update-unknown-request')==before and (state/'manifest.json').read_bytes()==manifest
    (repo/'owned.txt').write_text('Uncommitted fixture edit')
    assert 'source_checkout_has_local_changes' in (await (await http.get('/v1/runtime/updates/plan')).json())['restart_blockers']
    from jaeger_ai.core.gateway.caller_auth import client_headers
    assert (await http.get('/v1/runtime/updates/plan',headers=client_headers('a2a'))).status==403
    assert (await http.get('/v1/runtime/updates/plan?channel=arbitrary')).status==400
    assert (await http.post('/v1/runtime/updates/apply',json={})).status==404


def test_advertised_cli_check_uses_existing_owner_without_upgrade_or_migration(tmp_path,monkeypatch,capsys):
    from jaeger_ai.cli.verbs import update_verb
    monkeypatch.setattr(instance,'install_root',lambda:tmp_path)
    monkeypatch.setattr(instance,'detect_install_method',lambda:'dev-checkout')
    monkeypatch.setattr(instance,'user_instances_root',lambda:tmp_path/'owned-instances')
    monkeypatch.setattr(update_verb,'_run_upgrade',lambda *a,**k:pytest.fail('Read-only check must not upgrade'))
    monkeypatch.setattr(update_verb,'_migrate_instance_with_backup',lambda *a,**k:pytest.fail('Read-only check must not migrate'))
    assert update_verb._cmd_update_argv(['--check','--channel','latest'])==0
    assert 'install method' in capsys.readouterr().out
