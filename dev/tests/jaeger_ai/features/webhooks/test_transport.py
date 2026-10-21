"""Owned ephemeral loopback transport; dummy in-memory secret only."""
import hashlib
import hmac
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jaeger_ai.core.runtime.webhooks import serve


def test_transport_exact_signature_redacts_all_projected_strings_and_refuses_unscoped(capsys):
    calls = []
    secret = 'owned-fixture-secret'
    def accept(event):
        calls.append(event)
        return {'ok': True, 'status': 'awaiting_approval'}
    server = serve(accept, port=0, secret=secret)
    url = f'http://127.0.0.1:{server.server_port}'
    def post(path, body, headers):
        raw = json.dumps(body).encode()
        request = Request(url + path, data=raw, headers=headers)
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read())
    try:
        body = {'sender': 'owned-sender', 'delivery_id': 'owned-delivery', 'title': secret, 'prompt': 'Literal ' + secret}
        raw = json.dumps(body).encode()
        headers = {'Content-Type': 'application/json', 'X-Jaeger-Event': 'changed',
                   'X-Hub-Signature-256': 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}
        assert post('/hook/owned-sub', body, headers)['status'] == 'awaiting_approval'
        assert len(calls) == 1 and calls[0]['authenticated'] is True
        assert calls[0]['subscription_id'] == 'owned-sub'
        assert secret not in json.dumps(calls)
        assert calls[0]['title'] == '[redacted]' and calls[0]['prompt'] == 'Literal [redacted]'
        with pytest.raises(HTTPError) as caught:
            post('/hook/owned-sub', body, {**headers, 'X-Hub-Signature-256': 'sha256=prefix-' + secret + '-suffix'})
        assert caught.value.code == 401
        assert len(calls) == 1
        assert post('/hook', body, headers)['reason'] == 'subscription_required'
        assert post('/hook/owned-sub', {**body, 'delivery_id': secret}, {'Authorization': 'Bearer ' + secret, 'X-Jaeger-Event': 'changed'})['reason'] == 'invalid_event_identity'
        assert len(calls) == 1
    finally:
        server.shutdown(); server.server_close()
    assert secret not in capsys.readouterr().out


def test_transport_missing_secret_cannot_be_projected_as_authenticated():
    calls = []
    server = serve(lambda event: calls.append(event) or {'ok': False, 'reason': 'shared_secret_required'}, port=0)
    try:
        raw = json.dumps({'sender': 'owned-sender', 'delivery_id': 'owned-delivery', 'prompt': 'Fixture'}).encode()
        req = Request(f'http://127.0.0.1:{server.server_port}/hook/owned-sub', data=raw, headers={'X-Jaeger-Event': 'changed'})
        with urlopen(req, timeout=3) as response:
            assert json.loads(response.read())['reason'] == 'shared_secret_required'
        assert calls[0]['authenticated'] is False
    finally:
        server.shutdown(); server.server_close()
