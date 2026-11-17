"""CSRF 403 must consume the POST body so HTTP/1.1 keep-alive stays aligned."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from io import BytesIO
from types import SimpleNamespace



def test_consume_unread_request_body_drains_content_length():
    from api.helpers import consume_unread_request_body

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






