"""First-run WebUI routes forward to the owner-authenticated Gateway
(core/gateway/webapp/server.py) instead of being answered locally."""
from __future__ import annotations

from types import SimpleNamespace

from jaeger_ai.core.gateway.webapp import server


def _parsed(path):
    return SimpleNamespace(path=path, query="")


def test_first_run_get_is_proxied(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_gateway_proxy", lambda h, m, p, body=None: calls.append((m, p)) or True)
    assert server.handle_get(SimpleNamespace(headers={}), _parsed("/v1/first-run"))
    assert calls == [("GET", "/v1/first-run")]


def test_first_run_setup_and_skip_posts_are_proxied():
    import ast
    import inspect
    text = ast.unparse(ast.parse(inspect.getsource(server.handle_write)))
    assert "('/v1/first-run/setup', '/v1/first-run/skip')" in text
    assert "_gateway_proxy(h, 'POST', path, raw())" in text
