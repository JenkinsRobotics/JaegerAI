"""The WebUI session store is a read-through cache of the Gateway's sessions."""

import uuid

import pytest
from api import gateway_mirror, models

from jaeger_ai.contract.sessions import is_conversation_session


def _gw_session(sid, title="New conversation", messages=(), updated=100.0, **extra):
    return {
        "session_id": sid, "title": title, "profile": "jaeger", "workspace": "/w",
        "created_at": 1.0, "updated_at": updated, "metadata": extra.pop("metadata", {}),
        "messages": [
            {"id": i, "role": r, "content": c, "timestamp": 10.0 + i, "tool_calls": []}
            for i, (r, c) in enumerate(messages)
        ], **extra,
    }


@pytest.fixture
def gateway(monkeypatch):
    """A fake Gateway: {sid: session}. PATCH renames are recorded on ``store.renames``."""
    class Store(dict):
        renames: list = []

    store = Store()
    renames = store.renames = []

    def request(method, path, body=None):
        if method == "GET" and path == "/v1/sessions":
            return {"sessions": [{k: v for k, v in s.items() if k != "messages"} for s in store.values()]}
        if method == "GET" and path.startswith("/v1/sessions/"):
            return store.get(path.rsplit("/", 1)[1])
        if method == "PATCH":
            sid = path.rsplit("/", 1)[1]
            renames.append((sid, body["title"]))
            store[sid]["title"] = body["title"]
            return store[sid]
        return None

    monkeypatch.setattr(gateway_mirror, "_request", request)
    monkeypatch.setattr(gateway_mirror, "_fingerprints", {})
    monkeypatch.setattr(gateway_mirror, "_last_sweep", 0.0)
    return store


def _sid():
    return "mirror-" + uuid.uuid4().hex[:10]


def test_conversation_filter_skips_machine_sessions():
    assert is_conversation_session({"session_id": "abc", "metadata": {}})
    assert not is_conversation_session({"session_id": "task:task_1"})
    assert not is_conversation_session({"session_id": "heartbeat"})
    assert not is_conversation_session({"session_id": "x", "metadata": {"task_id": "t"}})
    assert not is_conversation_session({"session_id": "y", "metadata": {"native_session": "n"}})


def test_ide_conversation_appears_in_the_webui_store(gateway):
    sid = _sid()
    gateway[sid] = _gw_session(sid, "Fix the loop", [("user", "hi"), ("assistant", "hello")])
    assert gateway_mirror.mirror_all(force=True) >= 1
    s = models.get_session(sid)
    assert s.title == "Fix the loop"
    assert [(m["role"], m["content"]) for m in s.messages] == [("user", "hi"), ("assistant", "hello")]


def test_task_children_and_internal_lanes_are_not_mirrored(gateway):
    gateway["task:task_9"] = _gw_session("task:task_9", metadata={"task_id": "task_9"},
                                         messages=[("user", "machine work")])
    gateway["heartbeat"] = _gw_session("heartbeat", messages=[("user", "tick")])
    gateway_mirror.mirror_all(force=True)
    for sid in ("task:task_9", "heartbeat"):
        with pytest.raises(Exception):
            models.get_session(sid)


def test_gateway_transcript_replaces_local_drift_but_keeps_display_extras(gateway):
    sid = _sid()
    local = models.Session(session_id=sid, title="Old", messages=[
        {"role": "user", "content": "hi", "timestamp": 1, "attachments": ["a.png"]},
        {"role": "assistant", "content": "stale local answer", "timestamp": 2},
    ])
    local.save()
    gateway[sid] = _gw_session(sid, "Old", [("user", "hi"), ("assistant", "the real answer")])
    gateway_mirror.mirror_session(sid)
    s = models.get_session(sid)
    assert [m["content"] for m in s.messages] == ["hi", "the real answer"]
    assert s.messages[0].get("attachments") == ["a.png"]  # same message: extras survive


def test_gateway_title_wins_and_local_title_fills_a_generic_one(gateway):
    a, b = _sid(), _sid()
    models.Session(session_id=a, title="Local name", messages=[]).save()
    models.Session(session_id=b, title="Local name", messages=[]).save()
    gateway[a] = _gw_session(a, "Gateway name", [("user", "x")])
    gateway[b] = _gw_session(b, "New Conversation", [("user", "x")])
    gateway_mirror.mirror_session(a)
    gateway_mirror.mirror_session(b)
    assert models.get_session(a).title == "Gateway name"
    assert models.get_session(b).title == "Local name"
    assert (b, "Local name") in gateway.renames  # pushed to the owner


def test_a_session_with_a_stream_in_flight_is_left_alone(gateway):
    sid = _sid()
    s = models.Session(session_id=sid, title="Live", messages=[{"role": "user", "content": "partial"}])
    s.active_stream_id = "stream-1"
    s.save()
    gateway[sid] = _gw_session(sid, "Live", [("user", "partial"), ("assistant", "done")])
    assert gateway_mirror.mirror_session(sid) is False
    assert len(models.get_session(sid).messages) == 1


def test_unreachable_gateway_leaves_the_cache_serving(monkeypatch):
    monkeypatch.setattr(gateway_mirror, "_request", lambda *a, **k: None)
    monkeypatch.setattr(gateway_mirror, "_last_sweep", 0.0)
    assert gateway_mirror.mirror_all(force=True) == 0
    assert gateway_mirror.mirror_session("anything") is False


def test_unchanged_sessions_are_not_refetched(gateway, monkeypatch):
    sid = _sid()
    gateway[sid] = _gw_session(sid, "Once", [("user", "hi")], updated=5.0)
    gateway_mirror.mirror_all(force=True)
    fetched = []
    real = gateway_mirror._request
    monkeypatch.setattr(gateway_mirror, "_request", lambda m, p, b=None: (fetched.append(p), real(m, p, b))[1])
    monkeypatch.setattr(gateway_mirror, "_last_sweep", 0.0)
    gateway_mirror.mirror_all()
    assert fetched == ["/v1/sessions"]  # the list only; no per-session GET
