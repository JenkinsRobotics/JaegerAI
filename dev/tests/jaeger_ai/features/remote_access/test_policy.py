from jaeger_ai.features.remote_access import RemoteAccessPolicy


def test_loopback_is_allowed_without_remote_configuration() -> None:
    decision = RemoteAccessPolicy().authorize("127.0.0.1", {})
    assert decision.allowed


def test_remote_requires_enablement_network_and_token() -> None:
    disabled = RemoteAccessPolicy(token="secret")
    assert disabled.authorize("100.100.20.30", {"Authorization": "Bearer secret"}).status == 403

    enabled = RemoteAccessPolicy(token="secret", remote_enabled=True)
    assert enabled.authorize("192.168.1.2", {"Authorization": "Bearer secret"}).status == 403
    assert enabled.authorize("100.100.20.30", {}).status == 401
    assert enabled.authorize("100.100.20.30", {"Authorization": "Bearer wrong"}).status == 401
    assert enabled.authorize(
        "100.100.20.30", {"Authorization": "Bearer secret"}
    ).allowed


def test_forwarding_header_cannot_spoof_source_network() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=True)
    decision = policy.authorize(
        "192.168.1.2",
        {"Authorization": "Bearer secret", "X-Forwarded-For": "100.100.20.30"},
    )
    assert not decision.allowed


def test_signed_remote_session_is_accepted_and_tampering_is_rejected() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=True)
    session = policy.issue_session("owner")
    assert policy.authorize(
        "100.100.20.30", {"Cookie": f"jaeger_session={session}"}
    ).allowed
    assert not policy.authorize(
        "100.100.20.30", {"Cookie": f"jaeger_session={session}x"}
    ).allowed
