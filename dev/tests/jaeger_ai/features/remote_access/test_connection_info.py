"""Sharing a conversation reads the established origin without issuing access."""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_connection_info_is_read_only_and_contains_no_pairing_credential(monkeypatch):
    from jaeger_ai.features.remote_access import service
    from urllib.parse import urlparse

    sent = []
    helpers = ModuleType('api.helpers')
    helpers.j = lambda handler, payload: sent.append(payload) or True
    monkeypatch.setitem(sys.modules, 'api.helpers', helpers)
    monkeypatch.setattr(service, 'phone_url', lambda: 'https://studio.tailnet.ts.net:8443')
    monkeypatch.setattr(service, 'issue_pairing_token', lambda **kwargs: (_ for _ in ()).throw(AssertionError('Sharing cannot create access')))
    path = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api/remote_phone.py'
    spec = importlib.util.spec_from_file_location('connection_info_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.route(SimpleNamespace(), urlparse('/api/remote/connection-info'), 'GET')
    assert sent == [{'webui_origin':'https://studio.tailnet.ts.net:8443'}]
    assert module.route(SimpleNamespace(), urlparse('/api/remote/connection-info'), 'POST') is False
