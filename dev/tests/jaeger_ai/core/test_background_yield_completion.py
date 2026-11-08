"""Real returned producer can continue exact admitted background task."""
import json
import pytest
import time
from dev.tests.fixtures.owned_gateway import OwnedGateway

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_real_background_task_completes_across_yielded_slices(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_REVIEW_BACKGROUND_SLICES','1')
    monkeypatch.setenv('JAEGER_AUTO_MAX_STEPS','1')
    gateway=OwnedGateway(tmp_path)
    observed=[]
    try:
        gateway.start()
        gateway.request('/v1/sessions',{'session_id':'slices-parent','profile':'jaeger'})
        tid=gateway.request('/v1/tasks',{'session_id':'slices-parent','goal':'Create and verify report CONTRACT-FOREGROUND-RESUME',
            'request_id':'slices','proposal':True},caller='webui')[1]['task_id']
        task=gateway.request('/v1/tasks/'+tid)[1]
        assert task['payload']['background_admission_version']==1
        gateway.request('/v1/tasks/'+tid+'/approve',{'expected_updated_at':task['updated_at']},caller='webui')
        deadline=time.monotonic()+80
        while time.monotonic()<deadline:
            for approval in gateway.request('/v1/approvals')[1]['approvals']:
                assert approval['session_id'] == 'task:'+tid
                assert approval['request_id'] in {tid+':0', tid+':1'}
                assert approval['metadata']['tool'] == 'files.write_file'
                gateway.request('/v1/approvals/'+approval['approval_id'],{'approved':True,'decision':'once'})
            task=gateway.request('/v1/tasks/'+tid)[1]
            if task['payload'].get('attempt',0)>0:
                observed.append(task)
            if task['state'] in {'completed_verified','failed','needs_owner','blocked','paused','cancelled'}:
                break
            time.sleep(.03)
        (tmp_path/'review-result.json').write_text(json.dumps({'task':task,'observed':observed},indent=2))
        assert task['state']=='completed_verified', (task,(tmp_path/'gateway.log').read_text()[-15000:])
        rows=[gateway.request('/v1/requests/'+tid+':'+str(n))[1] for n in (0,1)]
        assert rows[0]['status']=='completed' and rows[0]['result']['halt_reason']=='yielded'
        assert rows[1]['status']=='completed' and not rows[1]['result'].get('halt_reason')
        assert rows[0]['native_run_id']==rows[1]['native_run_id']
        assert (tmp_path/'instances/contract/workspace/foreground-report.txt').read_text()=='FOREGROUND-FINAL-VERIFIED'
        (tmp_path/'review-receipts.json').write_text(json.dumps(rows,indent=2))
    finally:
        gateway.stop()
