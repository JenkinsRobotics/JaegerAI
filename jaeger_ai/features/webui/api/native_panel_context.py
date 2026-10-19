"""Native panel context inside the existing WebUI authentication boundary."""
from __future__ import annotations


def active_profile() -> str:
    from api.profiles import get_active_profile_name
    return get_active_profile_name() or "default"


def check_profile(handler) -> bool:
    """Precondition only: never select a profile or grant authentication."""
    expected = handler.headers.get("X-Jaeger-Expected-Profile")
    if expected is not None and expected != active_profile():
        from api.helpers import j
        j(handler, {"error": "WebUI profile changed; refresh before continuing"}, status=409)
        return False
    return True


def context(handler) -> dict:
    from api.auth import is_auth_enabled, parse_cookie, verify_session, csrf_token_for_session
    cookie = parse_cookie(handler) or getattr(handler, "_trusted_auth_session_cookie_value", None)
    csrf = csrf_token_for_session(cookie) if cookie and verify_session(cookie) else None
    return {"profile": active_profile(), "auth_enabled": is_auth_enabled(), "csrf_token": csrf}
