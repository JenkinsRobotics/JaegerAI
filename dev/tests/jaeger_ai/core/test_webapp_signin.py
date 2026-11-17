"""WebUI sign-in gate (core/gateway/webapp/jaeger_signin.py): password hashes,
session cookies, redirect safety and the failed-login limiter."""
from __future__ import annotations

import pytest

from jaeger_ai.core.gateway.webapp import jaeger_signin as signin

CFG = {"username": "matthew", "secret": b"k" * 32}


def test_password_hash_round_trip_and_rejects_wrong_password():
    stored = signin.hash_password("correct horse", salt=b"s" * 16)
    assert stored.startswith("scrypt$")
    assert signin.verify_password("correct horse", stored)
    assert not signin.verify_password("wrong", stored)
    assert not signin.verify_password("anything", "not-a-hash")


def test_session_cookie_is_signed_and_expires():
    token = signin.issue_session(CFG, now=1000.0)
    assert signin.verify_session(CFG, token, now=1001.0)
    assert not signin.verify_session(CFG, token, now=1000.0 + signin.SESSION_TTL + 1)
    payload, sig = token.rsplit(".", 1)
    assert not signin.verify_session(CFG, payload + "." + "0" * len(sig), now=1001.0)
    assert not signin.verify_session({**CFG, "username": "other"}, token, now=1001.0)
    assert not signin.verify_session(CFG, None)


@pytest.mark.parametrize("raw,expected", [
    ("/chat", "/chat"),
    (None, "/"),
    ("https://evil.example", "/"),
    ("//evil.example", "/"),
    ("/\\evil", "/"),
    (signin.LOGIN_PATH, "/"),
])
def test_next_redirect_stays_on_this_site(raw, expected):
    assert signin._safe_next(raw) == expected


def test_login_page_escapes_error_and_next():
    page = signin.login_html('/x"><img src=x>', "<b>bad</b>").decode()
    assert '<img src=x>' not in page and "<b>bad</b>" not in page
    assert "&lt;b&gt;bad&lt;/b&gt;" in page


def test_failed_logins_are_rate_limited_then_cleared():
    key = "test-client"
    signin.clear_failures(key)
    for i in range(signin.MAX_FAILS):
        assert not signin.rate_limited(key, now=100.0 + i)
        signin.record_failure(key, now=100.0 + i)
    assert signin.rate_limited(key, now=110.0)
    assert not signin.rate_limited(key, now=110.0 + signin.FAIL_WINDOW)
    signin.record_failure(key, now=200.0)
    signin.clear_failures(key)
    assert not signin.rate_limited(key, now=201.0)
