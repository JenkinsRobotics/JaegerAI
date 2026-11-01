"""A2A v1.0 over the official SDK, backed by the durable LedgerTaskStore.

Fake bridge only (no model, no live Gateway). Mirrors ARES's MCP acceptance:
admitted -> running -> completed with exact unseen content and a correlated
id, plus restart persistence, cancel, approval -> INPUT_REQUIRED, auth.
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from starlette.testclient import TestClient

from jaeger_ai.interfaces.a2a_server import build_app
from jaeger_ai.interfaces.a2a_task_store import LedgerTaskStore

TOKEN = "a2a-test-secret"
H = {"Authorization": f"Bearer {TOKEN}", "A2A-Version": "1.0"}


class Bridge:
    def __init__(self, mode="echo"):
        self.mode = mode
        self.turn_ids: list[str] = []
        self.sessions: list[str] = []
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.started = threading.Event()

    def turn(self, text, session, on_event=None, turn_id=None, **_kw):
        self.turn_ids.append(turn_id)
        self.sessions.append(session)
        on_event and on_event({"type": "queued", "session": session})
        self.started.set()
        if self.mode == "approval":
            on_event({"type": "state", "busy": True, "session": session,
                      "approval_id": "appr-1", "approval": "pending", "tool": "write_file"})
            self.release.wait(5)
            on_event({"type": "tool", "name": "write_file", "phase": "done"})
            return {"text": f"approved:{text}", "error": None, "request_id": turn_id}
        if self.mode == "block":
            self.cancelled.wait(5)
            return {"text": "", "error": "cancelled", "halt_reason": "interrupted",
                    "cancelled": True, "request_id": turn_id}
        if self.mode == "denied":
            return {"text": "", "error": "403 scope denied", "halt_code": "scope_denied"}
        if self.mode == "files":
            return {"text": "done", "error": None, "artifacts": ["/tmp/jaeger-a2a-out.txt"]}
        return {"text": f"echo:{text}", "error": None, "request_id": turn_id}

    def control(self, op, **payload):
        if op == "cancel":
            self.cancelled.set()


def _msg(text, context_id=None):
    m = {"messageId": uuid.uuid4().hex, "role": "ROLE_USER", "parts": [{"text": text}]}
    if context_id:
        m["contextId"] = context_id
    return m


def rpc(client, method, params, headers=H):
    r = client.post("/", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" not in body, body
    return body["result"]


def _app(tmp_path, bridge, db="t.sqlite3"):
    store = LedgerTaskStore(tmp_path / db)
    return build_app(client=bridge, tokens={"a2a": TOKEN}, task_store=store), store


def _wait_state(client, tid, want, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = rpc(client, "GetTask", {"id": tid})
        if task["status"]["state"] == want:
            return task
        time.sleep(0.05)
    raise AssertionError(f"{tid} never reached {want}: {task['status']}")


def test_v1_send_get_completed_with_exact_unseen_content_and_correlated_id(tmp_path):
    bridge = Bridge()
    nonce = uuid.uuid4().hex
    app, _ = _app(tmp_path, bridge)
    with TestClient(app) as c:
        res = rpc(c, "SendMessage", {"message": _msg(f"scratch {nonce}", "thread-7")})
        task = res["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert task["artifacts"][0]["parts"][0]["text"] == f"echo:scratch {nonce}"
        # A2A task id == Gateway request id (bridge turn_id) ; contextId -> a2a:<thread>
        assert bridge.turn_ids == [task["id"]]
        assert bridge.sessions == ["a2a:thread-7"]
        assert task["contextId"] == "thread-7"
        assert task["artifacts"][0]["metadata"]["jaeger.request_id"] == task["id"]
        got = rpc(c, "GetTask", {"id": task["id"]})
        assert got["status"]["state"] == "TASK_STATE_COMPLETED"
        listed = rpc(c, "ListTasks", {"contextId": "thread-7"})
        assert [t["id"] for t in listed["tasks"]] == [task["id"]]


def test_v03_method_names_still_work(tmp_path):
    app, _ = _app(tmp_path, Bridge())
    with TestClient(app) as c:
        r = c.post("/", headers={"Authorization": f"Bearer {TOKEN}"}, json={
            "jsonrpc": "2.0", "id": 2, "method": "message/send",
            "params": {"message": {"messageId": "m1", "role": "user", "kind": "message",
                                   "parts": [{"kind": "text", "text": "hi"}]}}})
    assert r.status_code == 200 and "error" not in r.json(), r.text
    assert r.json()["result"]["status"]["state"] == "completed"


def test_completed_task_survives_restart(tmp_path):
    app, store = _app(tmp_path, Bridge())
    with TestClient(app) as c:
        tid = rpc(c, "SendMessage", {"message": _msg("persist me")})["task"]["id"]
    store.close()
    app2, _ = _app(tmp_path, Bridge())
    with TestClient(app2) as c:
        task = rpc(c, "GetTask", {"id": tid})
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["artifacts"][0]["parts"][0]["text"] == "echo:persist me"


def test_inflight_task_after_restart_is_failed_execution_unknown(tmp_path):
    bridge = Bridge("block")
    app, store = _app(tmp_path, bridge)
    with TestClient(app) as c:
        tid = rpc(c, "SendMessage", {"message": _msg("long"),
                                     "configuration": {"returnImmediately": True}})["task"]["id"]
        assert bridge.started.wait(5)
        _wait_state(c, tid, "TASK_STATE_WORKING")
        # simulate a crash: a fresh process opens the DB while the task is WORKING
        reopened = LedgerTaskStore(tmp_path / "t.sqlite3")
        # let the original turn finish before the client shuts down, so
        # teardown never waits on a still-blocked executor thread
        bridge.cancelled.set()
        _wait_state(c, tid, "TASK_STATE_CANCELED")
    store.close()
    from a2a.types import TaskState
    (task,) = [t for owner in reopened._mem.tasks.values() for t in owner.values() if t.id == tid]
    assert task.status.state == TaskState.TASK_STATE_FAILED
    assert task.metadata["jaeger.execution_unknown"] is True
    assert tid in task.status.message.parts[0].text


def test_cancel_goes_to_native_cancel_and_reports_canceled(tmp_path):
    bridge = Bridge("block")
    app, _ = _app(tmp_path, bridge)
    with TestClient(app) as c:
        tid = rpc(c, "SendMessage", {"message": _msg("cancel me"),
                                     "configuration": {"returnImmediately": True}})["task"]["id"]
        assert bridge.started.wait(5)
        _wait_state(c, tid, "TASK_STATE_WORKING")
        r = c.post("/", headers=H, json={"jsonrpc": "2.0", "id": 3, "method": "CancelTask",
                                         "params": {"id": tid}})
        assert r.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED", r.text
        task = _wait_state(c, tid, "TASK_STATE_CANCELED")
    assert bridge.cancelled.is_set()
    assert task["id"] == bridge.turn_ids[0]


def test_owner_approval_surfaces_as_input_required_then_completes(tmp_path):
    bridge = Bridge("approval")
    app, _ = _app(tmp_path, bridge)
    with TestClient(app) as c:
        tid = rpc(c, "SendMessage", {"message": _msg("write it"),
                                     "configuration": {"returnImmediately": True}})["task"]["id"]
        waiting = _wait_state(c, tid, "TASK_STATE_INPUT_REQUIRED")
        assert waiting.get("metadata", {}).get("jaeger.approval_id") == "appr-1"
        assert "appr-1" in waiting["status"]["message"]["parts"][0]["text"]
        bridge.release.set()  # owner approved in Jaeger
        done = _wait_state(c, tid, "TASK_STATE_COMPLETED")
    assert done["artifacts"][0]["parts"][0]["text"] == "approved:write it"


def test_scope_denial_maps_to_auth_required(tmp_path):
    app, _ = _app(tmp_path, Bridge("denied"))
    with TestClient(app) as c:
        task = rpc(c, "SendMessage", {"message": _msg("forbidden")})["task"]
    assert task["status"]["state"] == "TASK_STATE_AUTH_REQUIRED"


def test_result_file_list_becomes_file_artifact(tmp_path):
    app, _ = _app(tmp_path, Bridge("files"))
    with TestClient(app) as c:
        task = rpc(c, "SendMessage", {"message": _msg("make file")})["task"]
    files = task["artifacts"][1]["parts"][0]
    assert files["url"] == "file:///tmp/jaeger-a2a-out.txt"
    assert files["filename"] == "jaeger-a2a-out.txt"


def test_card_is_v1_with_bearer_security(tmp_path):
    app, _ = _app(tmp_path, Bridge())
    with TestClient(app) as c:
        card = c.get("/.well-known/agent-card.json").json()
        anon = c.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "x"}})
    assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    assert card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "Bearer"
    assert "bearer" in card["securityRequirements"][0]["schemes"]
    assert card["capabilities"].get("pushNotifications", False) is False
    assert anon.status_code == 401
