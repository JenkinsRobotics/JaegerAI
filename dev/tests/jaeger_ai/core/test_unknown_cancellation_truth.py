"""Stop requests cannot erase an uncertain effect or execute another turn."""
import pytest

pytest_plugins = ('dev.tests.jaeger_ai.core.test_sessions_contract',)


@pytest.mark.asyncio
async def test_stop_retains_unknown_receipt_and_only_signals_original_scope(gw,monkeypatch):
    app,http=gw;sid='owned-unknown-stop';rid='owned-unknown-request'
    app.store.ensure_session(sid)
    app.store.admit_request(sid,'owned fixture, no real execution',request_id=rid,requested={'caller':'owner:webui'})
    app.store.complete_request(rid,status='execution_unknown',result={'error':'fixture uncertain effect','effect_outcome':'unknown'})
    app.store.ensure_session('owned-unrelated')
    other=app.store.admit_request('owned-unrelated','owned unrelated fixture',request_id='owned-unrelated-request')
    before=app.store.get_request(rid);other_before=app.store.get_request(other['request_id'])
    monkeypatch.setattr(app,'_start_admitted_turn',lambda *a:pytest.fail('Stop/reconciliation must never execute'))
    response=await http.post(f'/v1/sessions/{sid}/cancel',json={'request_id':rid})
    assert response.status==200
    receipt=await response.json()
    assert receipt['status']=='execution_unknown' and receipt['cancel_requested']
    assert receipt['cancellation_confirmed'] is False
    assert app.store.get_request(rid)==before
    assert app.store.get_request(other['request_id'])==other_before
    assert app._cancellations.is_cancelled(rid) and not app._cancellations.is_cancelled(other['request_id'])


@pytest.mark.asyncio
async def test_ordinary_admission_can_still_enter_cancelling_without_fabricated_settlement(gw):
    app,http=gw;sid='owned-ordinary-stop';rid='owned-ordinary-request'
    app.store.ensure_session(sid)
    app.store.admit_request(sid,'owned fixture, no worker started',request_id=rid)
    response=await http.post(f'/v1/sessions/{sid}/cancel',json={'request_id':rid})
    assert response.status==200
    receipt=await response.json()
    assert receipt['status']=='cancelling' and receipt['cancel_requested']
    assert receipt['cancellation_confirmed'] is False
    assert app.store.get_request(rid)['status']=='cancelling'
