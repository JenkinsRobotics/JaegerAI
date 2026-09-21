from __future__ import annotations

from jaeger_ai.features.remote_access.policy import RemoteAccessPolicy


def test_untrusted_network_denied() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=True)
    assert not policy.authorize("1.1.1.1", {"Authorization": "Bearer secret"}).allowed


def test_trusted_network_without_auth_denied() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=True)
    assert policy.authorize("100.100.1.1", {}).status == 401


def test_invalid_bearer_denied() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=True)
    assert policy.authorize("100.100.1.1", {"Authorization": "Bearer wrong"}).status == 401


def test_forged_session_cookie_denied() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=True)
    good = policy.issue_session("owner")
    assert policy.authorize("100.100.1.1", {"Cookie": f"jaeger_session={good}"}).allowed
    assert not policy.authorize("100.100.1.1", {"Cookie": f"jaeger_session={good[:-2]}aa"}).allowed


def test_disabled_remote_denied_on_tailnet() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=False)
    assert policy.authorize("100.100.1.1", {"Authorization": "Bearer secret"}).status == 403


def test_x_forwarded_for_cannot_grant_access() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=True)
    decision = policy.authorize(
        "8.8.8.8",
        {"Authorization": "Bearer secret", "X-Forwarded-For": "100.64.1.1"},
    )
    assert not decision.allowed
