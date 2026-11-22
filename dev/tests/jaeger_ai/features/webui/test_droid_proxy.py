"""The WebUI preserves the Droid service response across its Unix proxy."""
from io import BytesIO
from unittest.mock import Mock

import pytest

from jaeger_ai.core.gateway.webapp.jaeger_agents import _serve_droid


@pytest.mark.parametrize(("action", "status", "content_type", "payload"), [
    ("transcript", 200, "application/json", b'{"items":[]}'),
    ("camera.jpg", 404, "application/json", b'{"error":"no frame"}'),
    ("camera.jpg", 200, "image/jpeg", b"image bytes"),
])
def test_droid_proxy_forwards_status_and_body(monkeypatch, action, status, content_type, payload):
    import http.client
    import sys
    from types import ModuleType

    monkeypatch.setitem(sys.modules, "api.helpers", ModuleType("api.helpers"))
    sys.modules["api.helpers"].j = Mock()
    sys.modules["api.helpers"].read_body = Mock()
    response = Mock(status=status)
    response.getheader.return_value = content_type
    response.read.return_value = payload
    monkeypatch.setattr(http.client.HTTPConnection, "request", Mock())
    monkeypatch.setattr(http.client.HTTPConnection, "getresponse", Mock(return_value=response))
    close = Mock()
    monkeypatch.setattr(http.client.HTTPConnection, "close", close)
    handler = Mock(wfile=BytesIO())

    assert _serve_droid(handler, "GET", action)

    handler.send_response.assert_called_once_with(status)
    handler.send_header.assert_any_call("Content-Type", content_type)
    assert handler.wfile.getvalue() == payload
    close.assert_called_once()
