"""The WebUI must authenticate to the Jaeger Gateway with its caller token,
not a Hermes API_SERVER_KEY that a profile .env put into os.environ."""

from __future__ import annotations

from api import gateway_chat


def test_caller_token_wins_over_hermes_api_key(monkeypatch):
    monkeypatch.setattr("jaeger_ai.core.gateway.caller_auth.client_token",
                        lambda caller: "webui-caller-token" if caller == "webui" else None)
    assert gateway_chat._jaeger_gateway_token("stale-hermes-key") == "webui-caller-token"


def test_explicit_key_used_when_no_caller_token(monkeypatch):
    monkeypatch.setattr("jaeger_ai.core.gateway.caller_auth.client_token", lambda caller: None)
    assert gateway_chat._jaeger_gateway_token("explicit-key") == "explicit-key"


def test_empty_when_nothing_configured(monkeypatch):
    monkeypatch.setattr("jaeger_ai.core.gateway.caller_auth.client_token", lambda caller: None)
    assert gateway_chat._jaeger_gateway_token("") == ""
