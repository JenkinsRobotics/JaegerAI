from __future__ import annotations

import pytest

from jaeger_ai.features.oidc import service


def test_oidc_is_default_off_and_requires_allowlist(monkeypatch) -> None:
    for name in (
        "JAEGER_OIDC_ISSUER",
        "JAEGER_OIDC_CLIENT_ID",
        "JAEGER_OIDC_ALLOW_CLAIM",
        "JAEGER_OIDC_ALLOW_VALUES",
    ):
        monkeypatch.delenv(name, raising=False)
    assert service.is_oidc_enabled() is False
    with pytest.raises(service.OIDCConfigError):
        service.build_authorization_redirect("https://jaeger.example")


def test_oidc_config_and_redirect_path_are_bounded(monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_OIDC_ISSUER", "https://id.example/")
    monkeypatch.setenv("JAEGER_OIDC_CLIENT_ID", "jaeger")
    monkeypatch.setenv("JAEGER_OIDC_ALLOW_CLAIM", "email")
    monkeypatch.setenv("JAEGER_OIDC_ALLOW_VALUES", "owner@example.test")
    assert service.is_oidc_enabled() is True
    assert service._resolve_oidc_config()["issuer"] == "https://id.example"
    assert service._safe_next_path("//evil.example") == "/"
    assert service._safe_next_path("/sessions") == "/sessions"


def test_oidc_rejects_private_and_insecure_endpoints() -> None:
    with pytest.raises(service.OIDCAuthError, match="https"):
        service._validate_outbound_oidc_url("http://id.example/.well-known/openid-configuration")
    with pytest.raises(service.OIDCAuthError, match="private or local"):
        service._validate_outbound_oidc_url("https://127.0.0.1/keys")
