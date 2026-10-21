"""Passive catalog uses only registered origin-session attachments, no path grants."""
import base64
import hashlib

import pytest

pytest_plugins = ('dev.tests.jaeger_ai.core.test_sessions_contract',)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRj0AAAAASUVORK5CYII=')


@pytest.mark.asyncio
async def test_real_saved_media_search_preview_origin_and_no_request_admission(gw):
    from jaeger_ai.core.gateway.caller_auth import client_headers
    app, http = gw
    for sid in ('media-owned', 'media-other'):
        app.store.ensure_session(sid)
        response = await http.post(f'/v1/sessions/{sid}/attachments/upload', json={'name':'robot.png','mime':'image/png','data_base64':base64.b64encode(PNG).decode()})
        assert response.status == 201
    app.store.add_attachment('media-owned', {'original_filename':'active robot.svg','mime_type':'image/svg+xml','safe_path':'/not-a-grant'})
    before = app.store.list_messages('media-owned')
    response = await http.get('/v1/sessions/media-owned/files?kind=media&q=ROBOT')
    assert response.status==200
    value = await response.json()
    assert value['source']=='existing_session_attachments' and value['licensing']=='not_verified' and value['selection_attaches'] is False
    assert value['query']=='ROBOT' and len(value['files'])==1 and value['files'][0]['readable']
    row = value['files'][0]
    raw = await (await http.get('/v1/sessions/media-owned/files/'+row['attachment_id'])).json()
    assert base64.b64decode(raw['data_base64'])==PNG and raw['sha256']==hashlib.sha256(PNG).hexdigest()
    assert (await http.get('/v1/sessions/media-other/files/'+row['attachment_id'])).status==404
    assert (await http.get('/v1/sessions/media-owned/files?kind=media',headers=client_headers('a2a'))).status==403
    assert (await http.get('/v1/sessions/media-owned/files',params={'kind':'media','q':'x'*201})).status==400
    assert app.store.list_messages('media-owned')==before
    assert app.store.latest_request('media-owned') is None


def test_media_catalog_paging_is_literal_scoped_and_does_not_admit_paths(tmp_path):
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    gw_store = GatewaySessionStore(tmp_path/'catalog.sqlite3')
    gw_store.ensure_session('catalog-owned')
    for i in range(30):
        gw_store.add_attachment('catalog-owned',{'attachment_id':f'owned_{i:03d}','original_filename':'100%_robot.png','mime_type':'image/png','safe_path':'/arbitrary/model-path','size':3})
    a, cursor = gw_store.search_session_media('catalog-owned', '%_')
    b, end = gw_store.search_session_media('catalog-owned', '%_', after=cursor)
    assert len(a)==25 and len(b)==5 and end is None
    assert not {r['attachment_id'] for r in a}&{r['attachment_id'] for r in b}
    assert gw_store.search_session_media('other', '%_') == ([], None)

    gw_store.add_attachment('catalog-owned',{'original_filename':'Straße.png','mime_type':'image/png','safe_path':'/not-a-grant'})
    unicode_rows, _ = gw_store.search_session_media('catalog-owned', 'STRASSE')
    assert len(unicode_rows)==1 and unicode_rows[0]['original_filename']=='Straße.png'
