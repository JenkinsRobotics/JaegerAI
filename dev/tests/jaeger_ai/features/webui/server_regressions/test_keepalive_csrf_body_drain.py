"""CSRF 403 must consume the POST body so HTTP/1.1 keep-alive stays aligned."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from io import BytesIO
from types import SimpleNamespace

import pytest


def test_consume_unread_request_body_drains_content_length():
    from api.helpers import consume_unread_request_body, mark_request_body_consumed

    leftover = b'{"title": "POISON-BODY"}'
    handler = SimpleNamespace(
        command="POST",
        headers={"Content-Length": str(len(leftover)), "Transfer-Encoding": ""},
        rfile=BytesIO(leftover + b"POST /next HTTP/1.1\r\n"),
        close_connection=False,
    )
    consume_unread_request_body(handler)
    assert handler.rfile.read() == b"POST /next HTTP/1.1\r\n"
    consume_unread_request_body(handler)  # idempotent
    assert handler.close_connection is False


def test_consume_skips_when_already_marked():
    from api.helpers import consume_unread_request_body, mark_request_body_consumed

    leftover = b'{"keep": true}'
    handler = SimpleNamespace(
        command="POST",
        headers={"Content-Length": str(len(leftover))},
        rfile=BytesIO(leftover + b"GET / HTTP/1.1\r\n"),
        close_connection=False,
    )
    mark_request_body_consumed(handler)
    consume_unread_request_body(handler)
    assert handler.rfile.read().startswith(b'{"keep": true}')


def _start_handler_server(monkeypatch):
    import server
    from server import Handler
    import api.auth as auth
    from api.helpers import j, read_body

    monkeypatch.setattr(server, "check_auth", lambda handler, parsed: True)
    monkeypatch.setattr(auth, "check_auth", lambda handler, parsed: True)
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)

    def _agents(handler, parsed, method):
        if method != "POST":
            return False
        read_body(handler)
        j(handler, {"ok": True, "path": parsed.path})
        return True

    monkeypatch.setattr("api.jaeger_agents.route", _agents)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    return server, thread


def _post(conn, path, payload, *, csrf=None, host="127.0.0.1"):
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "Connection": "keep-alive",
        "Host": host,
        "Origin": f"http://{host}",
        "Cookie": "hermes_session=test.sig",
    }
    if csrf:
        headers["X-Hermes-CSRF-Token"] = csrf
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, data


def test_csrf_403_keep_alive_does_not_glue_json_onto_next_method(monkeypatch):
    import api.auth as auth

    monkeypatch.setattr(auth, "verify_session", lambda _c: True)
    monkeypatch.setattr(auth, "parse_cookie", lambda _h: "tok.sig")
    monkeypatch.setattr(auth, "verify_csrf_token", lambda _c, t: t == "good")

    server, thread = _start_handler_server(monkeypatch)
    host, port = server.server_address
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        host_hdr = f"{host}:{port}"
        st1, body1 = _post(conn, "/api/jaeger/sessions", {"title": "POISON-BODY"}, host=host_hdr)
        assert st1 == 403, body1[:200]
        assert b"Session expired" in body1 or b"error" in body1
        st2, body2 = _post(conn, "/api/jaeger/sessions", {"title": "POISON-BODY"}, host=host_hdr)
        assert st2 == 403, body2.decode("utf-8", "replace")[:400]
        assert b"Bad request syntax" not in body2
        assert b"Unsupported method" not in body2
        st3, body3 = _post(conn, "/api/jaeger/sessions", {"title": "ok"}, csrf="good", host=host_hdr)
        assert st3 == 200, body3.decode("utf-8", "replace")[:400]
        assert json.loads(body3).get("ok") is True
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize("rounds", [60])
def test_mixed_csrf_mutations_on_persistent_connection(monkeypatch, rounds):
    import api.auth as auth

    monkeypatch.setattr(auth, "verify_session", lambda _c: True)
    monkeypatch.setattr(auth, "parse_cookie", lambda _h: "tok.sig")
    monkeypatch.setattr(auth, "verify_csrf_token", lambda _c, t: t == "good")

    server, thread = _start_handler_server(monkeypatch)
    host, port = server.server_address
    malformed = 0
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        host_hdr = f"{host}:{port}"
        for i in range(rounds):
            csrf = "good" if i % 3 else None
            status, data = _post(
                conn, "/api/jaeger/sessions", {"n": i, "title": f"mix-{i}"}, csrf=csrf, host=host_hdr
            )
            text = data.decode("utf-8", "replace")
            if "Bad request syntax" in text or "Unsupported method" in text:
                malformed += 1
            if csrf:
                assert status == 200, text[:300]
            else:
                assert status == 403, text[:300]
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert malformed == 0
