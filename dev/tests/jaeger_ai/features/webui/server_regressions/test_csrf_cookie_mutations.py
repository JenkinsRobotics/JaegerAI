"""Cookie-authenticated mutations require CSRF even without Origin."""

from __future__ import annotations

from types import SimpleNamespace

class _Headers(dict):
    def get(self, key, default=""):
        return super().get(key, default)


def _handler(headers: dict) -> SimpleNamespace:
    return SimpleNamespace(headers=_Headers(headers))


def test_cookie_without_csrf_is_denied(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_check_same_origin_browser_request", lambda *_a, **_k: True)
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: True)
    monkeypatch.setattr("api.auth.parse_cookie", lambda _h: "tok.sig")
    monkeypatch.setattr("api.auth.verify_session", lambda _c: True)
    monkeypatch.setattr("api.auth.verify_csrf_token", lambda *_a, **_k: False)
    assert routes._check_csrf(_handler({})) is False


def test_cookie_with_invalid_csrf_is_denied(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_check_same_origin_browser_request", lambda *_a, **_k: True)
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: True)
    monkeypatch.setattr("api.auth.parse_cookie", lambda _h: "tok.sig")
    monkeypatch.setattr("api.auth.verify_session", lambda _c: True)
    monkeypatch.setattr("api.auth.verify_csrf_token", lambda _c, t: t == "good")
    assert routes._check_csrf(_handler({"X-Hermes-CSRF-Token": "bad"})) is False


def test_cookie_with_valid_csrf_succeeds(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_check_same_origin_browser_request", lambda *_a, **_k: True)
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: True)
    monkeypatch.setattr("api.auth.parse_cookie", lambda _h: "tok.sig")
    monkeypatch.setattr("api.auth.verify_session", lambda _c: True)
    monkeypatch.setattr("api.auth.verify_csrf_token", lambda _c, t: t == "good")
    assert routes._check_csrf(_handler({"X-Hermes-CSRF-Token": "good"})) is True


def test_bearer_without_cookie_is_exempt(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_check_same_origin_browser_request", lambda *_a, **_k: True)
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: True)
    monkeypatch.setattr("api.auth.parse_cookie", lambda _h: None)
    monkeypatch.setattr("api.auth.verify_session", lambda _c: False)
    h = _handler({"Authorization": "Bearer infra-token"})
    assert routes._check_csrf(h) is True


def test_unauthenticated_non_browser_without_cookie_passes_csrf_gate(monkeypatch):
    """Auth middleware still 401s protected routes; CSRF is not that layer."""
    import api.routes as routes

    monkeypatch.setattr(routes, "_check_same_origin_browser_request", lambda *_a, **_k: True)
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: True)
    monkeypatch.setattr("api.auth.parse_cookie", lambda _h: None)
    monkeypatch.setattr("api.auth.verify_session", lambda _c: False)
    assert routes._check_csrf(_handler({})) is True


def test_csrf_does_not_apply_to_pair_or_login():
    import api.routes as routes

    assert routes._csrf_exempt_path("/api/auth/login")
    assert routes._csrf_exempt_path("/api/remote/pair")
    assert not routes._csrf_exempt_path("/api/jaeger/sessions")
    assert not routes._csrf_exempt_path("/api/upload")
    assert not routes._csrf_exempt_path("/api/approval/respond")
