"""Every Jaeger client presents its own caller token to the Gateway."""

from __future__ import annotations

from urllib.request import Request

import pytest

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.client import GatewayTurnClient


def _bearer(name: str) -> str:
    return f"Bearer {caller_auth.read_token(name)}"


def test_turn_client_defaults_to_the_cli_caller(monkeypatch):
    monkeypatch.delenv("JAEGER_GATEWAY_CALLER", raising=False)
    client = GatewayTurnClient("http://127.0.0.1:1")
    assert client.caller == "cli"
    assert client._auth() == {"Authorization": _bearer("cli")}


@pytest.mark.parametrize("caller", ["bridge", "mcp", "webui"])
def test_turn_client_presents_the_named_caller(caller):
    assert GatewayTurnClient("http://127.0.0.1:1", caller=caller)._auth() == {
        "Authorization": _bearer(caller)}


def test_relayed_token_wins_over_the_process_caller():
    relayed = caller_auth.read_token("a2a")
    client = GatewayTurnClient("http://127.0.0.1:1", caller="bridge", token=relayed)
    assert client._auth() == {"Authorization": f"Bearer {relayed}"}


def test_process_caller_comes_from_env(monkeypatch):
    monkeypatch.setenv("JAEGER_GATEWAY_CALLER", "menubar")
    assert GatewayTurnClient("http://127.0.0.1:1")._auth() == {"Authorization": _bearer("menubar")}


def test_turn_client_sends_the_header_on_calls_and_streams(monkeypatch):
    from jaeger_ai.core.gateway import client as client_mod

    seen = []

    class _Resp:
        status = 200

        def read(self, *a):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(())

        def close(self):
            pass

    def fake_urlopen(req, timeout=None):
        seen.append(req.get_header("Authorization"))
        return _Resp()

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_urlopen)
    client = GatewayTurnClient("http://127.0.0.1:1", caller="bridge")
    client._call("GET", "/v1/sessions")
    list(client._events("s", 0))
    assert seen and all(value == _bearer("bridge") for value in seen)


def test_webui_proxy_authenticates_as_webui():
    from jaeger_ai.features.webui.api.jaeger_sessions import _add_caller_auth

    req = Request("http://127.0.0.1:8810/v1/sessions")
    _add_caller_auth(req)
    assert req.get_header("Authorization") == _bearer("webui")


def test_call_agent_without_registered_credential_sends_none():
    import importlib

    module = importlib.import_module("jaeger_agent.tools.call_agent")
    previous = module._GATEWAY_AUTH
    try:
        module.set_gateway_auth(None)
        assert module._caller_headers() == {}
    finally:
        module.set_gateway_auth(previous)


def test_call_agent_presents_jaegerd_and_the_bound_turn_actor():
    import importlib

    from jaeger_agent.tool_executor import caller_identity

    module = importlib.import_module("jaeger_agent.tools.call_agent")
    previous = module._GATEWAY_AUTH
    try:
        module.set_gateway_auth(lambda: caller_auth.client_headers("jaegerd"))
        with caller_identity("mcp"):
            headers = module._caller_headers()
        assert headers["Authorization"] == _bearer("jaegerd")
        assert headers["X-Jaeger-Actor"] == "mcp"
    finally:
        module.set_gateway_auth(previous)


def test_bridge_client_refuses_to_relay_without_the_caller_token(monkeypatch):
    """An MCP/A2A turn over the bridge socket must carry that caller's token;
    without it the client fails instead of borrowing the bridge identity."""
    from jaeger_ai.features.webui.adapter import bridge_client

    monkeypatch.setattr(caller_auth, "client_token", lambda name: None)
    client = bridge_client.BridgeClient.__new__(bridge_client.BridgeClient)
    with pytest.raises(bridge_client.HermesWebUIAdapterBridgeError, match="caller token"):
        client.turn("hi", session="mcp:x", gateway_caller="mcp")
