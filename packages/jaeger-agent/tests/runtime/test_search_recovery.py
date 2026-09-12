"""Search outcome and configured endpoint recovery contracts."""
import importlib
import requests
import pytest

web = importlib.import_module('jaeger_agent.tools.web')


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    web._searx_retry_at.clear()
    web._searx_probing.clear()
    monkeypatch.setattr(web, 'is_interrupted', lambda: False)
    yield
    web._searx_retry_at.clear()
    web._searx_probing.clear()


def test_empty_results_are_not_an_outage(monkeypatch):
    def empty(*args):
        raise web.NoSearchResults('no matches')
    def down(*args):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr(web, '_BACKENDS', [('down', down), ('responded', empty)])
    result = web.web_search('very specific query')
    assert result['status'] == 'no_results'
    assert result['ok'] and result['results'] == []
    assert result['empty_backends'] == ['responded']
    assert 'offline' in result['tried'][0]


def test_outage_stays_failure(monkeypatch):
    def down(*args):
        raise requests.ConnectionError('offline')
    monkeypatch.setattr(web, '_BACKENDS', [('down', down)])
    assert web.web_search('query')['ok'] is False


def test_searx_cooldown_recovers_after_deadline(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL', 'http://configured.test')
    monkeypatch.delenv('SEARXNG_URL_FALLBACK', raising=False)
    now = [100.0]
    monkeypatch.setattr(web.time, 'monotonic', lambda: now[0])
    calls = []
    def get(*args, **kwargs):
        calls.append(args[0])
        if len(calls) == 1:
            raise requests.ConnectTimeout('down')
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'results': [{'title': 'Source', 'url': 'https://source.test'}]}
        return Response()
    monkeypatch.setattr(requests, 'get', get)
    for _ in range(2):
        with pytest.raises(RuntimeError): web._backend_searxng('q', 2)
    assert len(calls) == 1
    now[0] += 61
    assert web._backend_searxng('q', 2)[0]['title'] == 'Source'
    assert len(calls) == 2
