"""Honcho 3.0.10 contract from the deployed server's OpenAPI document."""
from jaeger_ai.features.shared_memory.honcho_client import HonchoClient


def test_named_lookup_uses_filtered_read_without_creating(monkeypatch):
    c = HonchoClient(base_url='http://test.invalid')
    calls = []
    def request(method, path, body):
        calls.append((method, path, body))
        return {'items': [{'id': 'record'}]}
    monkeypatch.setattr(c, '_request', request)
    assert c.get_peer('record') == {'id': 'record'}
    assert calls == [('POST', c._ws()+'/peers/list', {'filters': {'id': 'record'}})]
    assert c.get_session('absent')['error'].startswith('HTTP 404')


def test_message_read_follows_pages_and_fails_closed(monkeypatch):
    c = HonchoClient(base_url='http://test.invalid')
    calls = []
    def request(method, path, body):
        calls.append(path)
        return {'items': [{'content': str(len(calls))}], 'pages': 2}
    monkeypatch.setattr(c, '_request', request)
    assert c.list_messages('topic')['items'] == [{'content':'1'}, {'content':'2'}]
    assert '?page=2&size=100' in calls[-1]
    monkeypatch.setattr(c, '_request', lambda *a: {'items': []})
    assert 'error' in c.list_messages('topic')


def test_message_creation_accepts_api_201_array_without_retry(monkeypatch):
    client = HonchoClient(base_url='http://test.invalid')
    calls = []
    def request(method, path, body):
        calls.append((method, path, body))
        return [{'id': 'receipt', 'content': 'public claim'}]
    monkeypatch.setattr(client, '_request', request)
    assert client.add_message('s', 'p', 'public claim') == {'messages': [{'id': 'receipt', 'content': 'public claim'}]}
    assert len(calls) == 1
