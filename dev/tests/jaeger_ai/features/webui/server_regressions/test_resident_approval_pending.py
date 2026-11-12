"""Stock /api/approval/pending and respond see runner-local and Gateway approvals."""

from __future__ import annotations

from types import SimpleNamespace


def test_resident_resolve_prefers_runner(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_runner_local_resolve", lambda *_a, **_k: True)
    monkeypatch.setattr(routes, "_gateway_store_resolve", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("gateway")))
    assert routes._resident_resolve_approval("sid", "perm9", "once") is True


def test_resident_resolve_falls_through_to_gateway(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_runner_local_resolve", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "_gateway_store_resolve", lambda *_a, **_k: True)
    assert routes._resident_resolve_approval("sid", "approval_abc", "deny") is True
