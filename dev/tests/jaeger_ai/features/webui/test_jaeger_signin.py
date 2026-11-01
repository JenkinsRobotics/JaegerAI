"""Jaeger WebUI sign-in gate: hashing, sessions, host check, loopback exemptions."""
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

WEBUI = Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui"
sys.path.insert(0, str(WEBUI))
from api import jaeger_signin as js  # noqa: E402

PUBLIC = "https://mac.tail0.ts.net:8443"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "webui-auth.json"
    path.write_text(json.dumps({"webui": {"public_url": PUBLIC, "basic_auth": {
        "username": "matthew", "password_hash": js.hash_password("s3cret-pass"), "secret": "x" * 44}}}))
    monkeypatch.setenv("JAEGER_WEBUI_AUTH_CONFIG", str(path))
    monkeypatch.setenv("JAEGER_WEBUI_SIGNIN", "1")
    js._cache.update(mtime=None, cfg=None)
    js._fails.clear()
    return js.load_config()


class H:
    def __init__(self, path, headers=None, ip="127.0.0.1", command="GET", body=b""):
        self.path, self.command = path, command
        self.client_address = (ip, 1)
        self.headers = {"Host": "127.0.0.1:8790", **(headers or {})}
        if body:
            self.headers["Content-Length"] = str(len(body))
        self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
        self.status, self.sent = None, {}

    def send_response(self, s): self.status = s
    def send_header(self, k, v): self.sent[k] = v
    def end_headers(self): pass


def run(h):
    return js.gate(h, urlparse(h.path))


REMOTE = {"Host": "mac.tail0.ts.net:8443", "X-Forwarded-For": "100.1.2.3", "X-Forwarded-Proto": "https"}


def test_hash_roundtrip_and_no_plaintext():
    h = js.hash_password("pw")
    assert h.startswith("scrypt$") and "pw" not in h.split("$")[-1]
    assert js.verify_password("pw", h) and not js.verify_password("nope", h)
    assert js.hash_password("pw") != h  # random salt


def test_no_config_is_passthrough(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_WEBUI_AUTH_CONFIG", str(tmp_path / "missing.json"))
    js._cache.update(mtime=None, cfg=None)
    assert run(H("/", REMOTE))


def test_loopback_clients_exempt(cfg):
    for path in ("/", "/api/sessions", "/v1/ui/layout"):
        assert run(H(path)) is True
    assert run(H("/", {"Host": "localhost:8790"})) is True


def test_wrong_host_400(cfg):
    h = H("/", {"Host": "evil.example.com"})
    assert run(h) is False and h.status == 400
    h = H("/", {**REMOTE, "Host": "evil.example.com"})
    assert run(h) is False and h.status == 400


def test_remote_page_redirects_api_401(cfg):
    h = H("/work?x=1", REMOTE)
    assert run(h) is False and h.status == 302 and h.sent["Location"].startswith("/jaeger/login?next=/work")
    h = H("/api/sessions", REMOTE)
    assert run(h) is False and h.status == 401


def test_non_loopback_peer_is_remote(cfg):
    h = H("/", {"Host": "127.0.0.1:8790"}, ip="100.1.2.3")
    assert run(h) is False and h.status == 302


def test_status_reports_basic(cfg):
    h = H("/api/auth/status", REMOTE)
    assert run(h) is False
    body = json.loads(h.wfile.getvalue())
    assert body["auth_required"] is True and body["auth_providers"] == ["basic"]


def test_login_flow_and_cookie(cfg):
    h = H("/jaeger/login", REMOTE, command="POST", body=b"username=matthew&password=s3cret-pass&next=/work")
    assert run(h) is False and h.status == 303 and h.sent["Location"] == "/work"
    cookie = h.sent["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie
    value = cookie.split(";")[0]
    assert run(H("/api/sessions", {**REMOTE, "Cookie": value})) is True


def test_open_redirect_blocked(cfg):
    h = H("/jaeger/login", REMOTE, command="POST", body=b"username=matthew&password=s3cret-pass&next=//evil.com")
    run(h)
    assert h.sent["Location"] == "/"


def test_bad_password_and_rate_limit(cfg):
    for _ in range(js.MAX_FAILS):
        h = H("/jaeger/login", REMOTE, command="POST", body=b"username=matthew&password=bad")
        run(h)
        assert h.status == 401
    h = H("/jaeger/login", REMOTE, command="POST", body=b"username=matthew&password=s3cret-pass")
    run(h)
    assert h.status == 429


def test_tampered_or_expired_session(cfg):
    good = js.issue_session(cfg)
    assert js.verify_session(cfg, good)
    assert not js.verify_session(cfg, good[:-1] + ("0" if good[-1] != "0" else "1"))
    assert not js.verify_session(cfg, js.issue_session(cfg, now=1.0))


def test_logout_clears_cookie(cfg):
    h = H("/jaeger/logout", REMOTE)
    assert run(h) is False and "Max-Age=0" in h.sent["Set-Cookie"]


def test_server_wires_gate_before_auth():
    text = (WEBUI / "server.py").read_text()
    assert text.count("if not jaeger_signin_gate(self, parsed): return") == 2


def _disabled(tmp_path, monkeypatch, enabled=None):
    ba = {"username": "matthew", "password_hash": js.hash_password("s3cret-pass"), "secret": "x" * 44}
    if enabled is not None:
        ba["enabled"] = enabled
    path = tmp_path / "auth-off.json"
    path.write_text(json.dumps({"webui": {"public_url": PUBLIC, "basic_auth": ba}}))
    monkeypatch.setenv("JAEGER_WEBUI_AUTH_CONFIG", str(path))
    monkeypatch.delenv("JAEGER_WEBUI_SIGNIN", raising=False)
    js._cache.update(mtime=None, cfg=None)


@pytest.mark.parametrize("enabled", [None, False])
def test_disabled_by_default_no_login(tmp_path, monkeypatch, enabled):
    _disabled(tmp_path, monkeypatch, enabled)
    assert run(H("/work", REMOTE)) is True
    assert run(H("/api/sessions", REMOTE)) is True
    h = H("/api/auth/status", REMOTE)
    assert run(h) is False
    body = json.loads(h.wfile.getvalue())
    assert body["auth_required"] is False and body["auth_providers"] == []


def test_disabled_still_checks_host(tmp_path, monkeypatch):
    _disabled(tmp_path, monkeypatch)
    h = H("/", {**REMOTE, "Host": "evil.example.com"})
    assert run(h) is False and h.status == 400


def test_enabled_flag_and_env(tmp_path, monkeypatch):
    _disabled(tmp_path, monkeypatch, True)
    h = H("/", REMOTE)
    assert run(h) is False and h.status == 302
    _disabled(tmp_path, monkeypatch, False)
    monkeypatch.setenv("JAEGER_WEBUI_SIGNIN", "1")
    h = H("/", REMOTE)
    assert run(h) is False and h.status == 302
