"""WebUI approval path for Jaeger Gateway cards.

* The parent chat's pending check also returns a background worker's card
  (filed under ``task:<id>``, linked by ``origin.parent_session_id``).
* /api/approval/respond resolves Gateway cards by approval_id through
  POST /v1/approvals/{id} with the WebUI's caller token, with or without a
  run_id, instead of answering 409 gateway_run_unavailable.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

ORIGIN = {"task_id": "task_abc", "child_session_id": "task:task_abc",
          "agent_id": "native:jaeger", "parent_session_id": "chat-1"}
ROW = {"approval_id": "approval_child", "session_id": "task:task_abc", "status": "pending",
       "prompt": "Allow files.write_file? /tmp/x", "options": ["once", "session", "deny"],
       "metadata": {"tool": "files.write_file", "target": "/tmp/x", "reason": "WRITE_LOCAL", "origin": ORIGIN},
       "origin": ORIGIN}


class _Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _fake_gateway(monkeypatch, rows):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(SimpleNamespace(url=req.full_url, method=req.get_method(),
                                     headers={k.lower(): v for k, v in req.header_items()},
                                     body=json.loads(req.data.decode()) if req.data else None))
        if req.get_method() == "GET":
            return _Resp({"approvals": rows})
        return _Resp({"resolved": True})

    monkeypatch.setattr("api.jaeger_sessions.gateway_base", lambda: "http://127.0.0.1:18890")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    import api.routes as routes
    monkeypatch.setattr(routes, "_webui_gateway_auth", lambda: {"Authorization": "Bearer test-webui"})
    return calls


def test_parent_pending_includes_the_workers_card(monkeypatch):
    import api.routes as routes
    calls = _fake_gateway(monkeypatch, [ROW])
    pending = routes._gateway_store_pending("chat-1")
    assert pending["approval_id"] == "approval_child"
    assert pending["origin"] == ORIGIN and pending["session_id"] == "chat-1"
    assert calls[0].url.endswith("/v1/approvals?session_id=chat-1")
    assert routes._gateway_store_pending("chat-2") is None


def test_respond_resolves_gateway_card_by_id_with_auth(monkeypatch):
    import api.routes as routes
    calls = _fake_gateway(monkeypatch, [ROW])
    sent = {}
    monkeypatch.setattr(routes, "j", lambda _h, payload, status=200: sent.update(payload=payload, status=status))
    for body in ({"session_id": "chat-1", "approval_id": "approval_child", "choice": "deny"},
                 {"session_id": "chat-1", "approval_id": "approval_child", "choice": "once", "run_id": "r-1"}):
        sent.clear(); calls.clear()
        routes._handle_approval_respond(object(), body)
        assert sent["status"] == 200 and sent["payload"]["ok"] is True, sent
        post = [c for c in calls if c.method == "POST"][0]
        assert post.url.endswith("/v1/approvals/approval_child")
        assert post.headers["authorization"] == "Bearer test-webui"
        assert post.body["decision"] == body["choice"]


def test_respond_leaves_other_sessions_cards_alone(monkeypatch):
    import api.routes as routes
    _fake_gateway(monkeypatch, [ROW])
    assert routes._respond_gateway_store_approval("chat-2", "approval_child", "once") is None
