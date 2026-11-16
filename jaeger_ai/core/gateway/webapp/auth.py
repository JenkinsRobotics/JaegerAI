"""Hermes password/session auth is retired. Remote access goes through the
Tailscale front door plus the optional Jaeger sign-in gate (jaeger_signin)."""
from __future__ import annotations


def is_auth_enabled() -> bool:
    return False


def parse_cookie(handler):
    return None


def verify_session(cookie) -> bool:
    return False


def csrf_token_for_session(cookie) -> str:
    return ""


def list_sessions() -> list:
    return []


def revoke_session_prefix(prefix: str) -> int:
    return 0


def revoke_remote_sessions() -> int:
    return 0


def _retired(*_a, **_k):
    raise RuntimeError("Hermes WebUI auth was retired (R11); use the Jaeger sign-in gate")


create_session = _auth_cookie_header = _queue_pending_cookie = _retired
