"""Chat-study gaps: reasoning duration and persisted response parts."""
from __future__ import annotations

import pytest

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def _gateway(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    gateway.store.ensure_session("s1")
    return gateway


def _events(gateway, name=None):
    rows = gateway.store.replay_events("s1", 0)["events"]
    return [e for e in rows if name is None or e["event"] == name]


def test_reasoning_done_once_per_run_with_duration(tmp_path):
    gateway = _gateway(tmp_path)
    callbacks, finish = gateway._turn_stream_callbacks("s1", "r1")
    callbacks.reasoning("thinking a")
    callbacks.reasoning("thinking b")
    callbacks.stream_delta("Answer")
    callbacks.reasoning("again")
    finish()
    done = _events(gateway, "turn.reasoning.done")
    assert len(done) == 2
    assert all(d["data"]["request_id"] == "r1" and d["data"]["duration_ms"] >= 0 for d in done)
    names = [e["event"] for e in _events(gateway)]
    assert names.index("turn.reasoning.done") < names.index("turn.delta")


def test_project_parts_folds_events_in_order():
    from jaeger_ai.core.gateway.turn_parts import project_parts

    parts = project_parts([
        {"event": "turn.reasoning", "data": {"text": "a"}, "timestamp": 1.0},
        {"event": "turn.reasoning", "data": {"text": "b"}, "timestamp": 1.5},
        {"event": "turn.reasoning.done", "data": {"started_at": 1.0, "duration_ms": 900}},
        {"event": "tool.started", "data": {"call_id": "c1", "tool": "read_file", "input": "x.py"}},
        {"event": "tool.completed", "data": {"call_id": "c1", "tool": "read_file", "elapsed_s": 0.2}},
        {"event": "turn.delta", "data": {"delta": "Hel", "content_type": "provisional", "item_id": "answer-1"}},
        {"event": "turn.delta", "data": {"delta": "lo", "content_type": "provisional", "item_id": "answer-1"}},
    ], "Hello")
    assert parts == [
        {"type": "reasoning", "text": "ab", "started_at": 1.0, "duration_ms": 900},
        {"type": "tool", "call_id": "c1", "tool": "read_file", "status": "done", "input": "x.py", "elapsed_s": 0.2},
        {"type": "text", "text": "Hello", "role": "final", "item_id": "final"},
    ]


def test_project_parts_keeps_commentary_actions_and_one_final_in_order():
    from jaeger_ai.core.gateway.turn_parts import project_parts

    parts = project_parts([
        {"event": "turn.delta", "data": {"delta": "I’ll inspect the build.", "content_type": "provisional", "item_id": "text-1"}},
        {"event": "turn.progress", "data": {"message": "Reading pyproject.toml", "content_type": "commentary"}},
        {"event": "tool.started", "data": {"call_id": "c1", "tool": "read_file", "input": "pyproject.toml"}},
        {"event": "tool.completed", "data": {"call_id": "c1", "tool": "read_file", "summary": "Read pyproject.toml"}},
        {"event": "turn.delta", "data": {"delta": "The project uses Python 3.12.", "content_type": "provisional", "item_id": "text-2"}},
    ], "The project uses Python 3.12.")

    assert [(part["type"], part.get("role"), part.get("summary")) for part in parts] == [
        ("text", "commentary", None),
        ("progress", None, None),
        ("tool", None, "Read pyproject.toml"),
        ("text", "final", None),
    ]
    assert parts[-1]["text"] == "The project uses Python 3.12."


def test_tool_start_has_useful_public_progress_and_stable_activity_id(tmp_path):
    gateway = _gateway(tmp_path)
    callbacks, finish = gateway._turn_stream_callbacks("s1", "r1")
    callbacks.stream_delta("I’ll check it.")
    callbacks.tool_progress("read_file", "start", {"path": "pyproject.toml"})
    callbacks.tool_done("read_file", {"path": "pyproject.toml"}, {}, True, None, 0.2)
    finish()
    events = _events(gateway)
    progress = next(event for event in events if event["event"] == "turn.progress")["data"]
    started = next(event for event in events if event["event"] == "tool.started")["data"]
    completed = next(event for event in events if event["event"] == "tool.completed")["data"]
    delta = next(event for event in events if event["event"] == "turn.delta")["data"]
    assert progress["message"] == "Reading pyproject.toml"
    assert progress["activity_id"] == started["activity_id"] == completed["activity_id"]
    assert completed["summary"] == "Read pyproject.toml"
    assert delta["content_type"] == "provisional" and delta["item_id"].startswith("text_")


def test_completed_turn_persists_parts_on_the_assistant_message(tmp_path):
    gateway = _gateway(tmp_path)
    store = gateway.store
    store.admit_request("s1", "hello", request_id="r1")
    rid = "r1"
    callbacks, finish = gateway._turn_stream_callbacks("s1", rid)
    callbacks.reasoning("plan")
    callbacks.stream_delta("Hi there")
    finish()
    store.complete_request(rid, status="completed", result={}, assistant_text="Hi there")
    message = store.get_session("s1")["messages"][-1]
    assert message["role"] == "assistant"
    assert [p["type"] for p in message["parts"]] == ["reasoning", "text"]
    assert message["parts"][0]["duration_ms"] >= 0
    assert message["parts"][1] == {"type": "text", "text": "Hi there", "role": "final", "item_id": "final"}


def test_handoffs_stream_on_the_origin_turn_and_persist_as_parts(tmp_path):
    gateway = _gateway(tmp_path)
    store = gateway.store
    store.admit_request("s1", "ask research", request_id="r1")
    record = {"id": "handoff_1", "session_id": "s1", "parent_run_id": "r1", "to_agent_id": "native:research",
              "status": "admitted", "metadata": {"target_display": "Research"}}
    gateway._publish_handoff("agent.handoff", record)
    gateway._publish_handoff("agent.handoff.finished", {**record, "status": "completed"})
    on_chat = [e for e in _events(gateway) if e["event"].startswith("agent.handoff") and e["session_id"] == "s1"]
    assert [e["data"]["request_id"] for e in on_chat] == ["r1", "r1"]
    assert sum(e["session_id"] == "*" and e["event"].startswith("agent.handoff")
               for e in _events(gateway)) == 2  # global copies are unchanged

    store.complete_request("r1", status="completed", result={}, assistant_text="Research says hi")
    parts = store.get_session("s1")["messages"][-1]["parts"]
    assert [(p["type"], p.get("direction"), p.get("agent_name")) for p in parts] == [
        ("handoff", "to", "Research"), ("handoff", "from", "Research"), ("text", None, None)]


def test_handoff_without_a_matching_origin_turn_stays_global(tmp_path):
    gateway = _gateway(tmp_path)
    gateway._publish_handoff("agent.handoff", {"id": "h2", "session_id": "s1", "parent_run_id": "nope",
                                               "to_agent_id": "native:research"})
    assert [e["session_id"] for e in _events(gateway, "agent.handoff")] == ["*"]


@pytest.mark.asyncio
async def test_patch_session_model_is_validated_and_drives_turn_defaults(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.runtime import truth

    monkeypatch.setattr(truth, "provider_model_inventory", lambda *a, **k: {"providers": [
        {"id": "ollama", "reachable": True, "models": [{"id": "qwen3:4b"}]},
        {"id": "lmstudio", "reachable": False, "models": [{"id": "offline-model"}]},
    ]})
    gateway = _gateway(tmp_path)
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        ok = await client.patch("/v1/sessions/s1", json={"model": "@ollama:qwen3:4b"})
        assert ok.status == 200
        assert (await ok.json())["metadata"]["model"] == "qwen3:4b"
        settings = await client.get("/v1/sessions/s1?view=settings")
        assert await settings.json() == {"session_id": "s1", "model": "qwen3:4b", "provider": "ollama", "model_choice_revision":1,"atomic_model_operations":True}
        assert (await client.patch("/v1/sessions/s1", json={"model": "offline-model"})).status == 400
        assert (await client.patch("/v1/sessions/s1", json={"model": "nope"})).status == 400
        assert (await client.patch("/v1/sessions/s1", json={"model": 3})).status == 400
    meta = gateway.store.get_session("s1")["metadata"]
    assert (meta["model"], meta["provider"]) == ("qwen3:4b", "ollama")
    admitted = gateway.store.admit_request("s1", "hi", request_id="rm")
    assert "qwen3:4b" in str(admitted)  # the frozen execution input uses the session model
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        cleared = await client.patch("/v1/sessions/s1", json={"model": None})
        assert cleared.status == 200 and (await cleared.json())["metadata"].get("model") is None


def test_reasoning_pieces_are_coalesced_and_flushed_before_other_events(tmp_path):
    gateway = _gateway(tmp_path)
    callbacks, finish = gateway._turn_stream_callbacks("s1", "rc")
    for piece in "thinking hard about it":
        callbacks.reasoning(piece)
    callbacks.stream_delta("Answer")
    callbacks.reasoning("more")
    finish()
    events = [e for e in _events(gateway) if e["data"].get("request_id") == "rc"]
    names = [e["event"] for e in events]
    reasoning = [e["data"]["text"] for e in events if e["event"] == "turn.reasoning"]
    assert "".join(reasoning) == "thinking hard about itmore"
    assert len(reasoning) <= 3  # 23 pieces -> a few frames, not one per piece
    assert names[-3:] == ["turn.reasoning", "turn.reasoning.done", "turn.delta"] or \
        names.index("turn.delta") > names.index("turn.reasoning.done")
    first_delta = names.index("turn.delta")
    assert set(names[:first_delta]) >= {"turn.reasoning", "turn.reasoning.done"}


def test_sent_marker_requires_durable_recipient_post(tmp_path, monkeypatch):
    from jaeger_ai.core.gateway.turn_parts import project_parts
    gateway = _gateway(tmp_path)
    record = {"id": "handoff_delivery", "session_id": "s1", "parent_run_id": "r1",
              "from_agent_id": "native:jaeger", "to_agent_id": "native:builder",
              "task": "Owned fixture message", "status": "admitted"}
    gateway.store.admit_request("s1", "ask builder", request_id="r1")
    gateway._publish_handoff("agent.handoff", record)
    assert project_parts(_events(gateway))[0]["status"] == "admitted"
    gateway._post_handoff_request(record)
    parts = project_parts(_events(gateway))
    assert [p["status"] for p in parts] == ["delivered"]
    messages = gateway.store.get_session("agent-native:builder")["messages"]
    assert len(messages) == 1 and messages[0]["content"] == record["task"]
    assert messages[0]["links"]["handoff_id"] == record["id"]
    # Failed transcript persistence cannot publish a success notification.
    monkeypatch.setattr(gateway.store, "append_handoff_post_once", lambda *a, **k: (_ for _ in ()).throw(OSError("fixture unavailable")))
    before = len(_events(gateway))
    gateway._post_handoff_request({**record, "id": "handoff_failed_delivery"})
    assert len(_events(gateway)) == before


@pytest.mark.asyncio
async def test_idle_stream_keepalive_is_not_a_durable_event(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.core.gateway.caller_auth import client_headers
    app = _gateway(tmp_path)
    app._sse_keepalive_seconds = .01
    before = len(_events(app))
    async with TestClient(TestServer(app.app), headers=client_headers('webui')) as client:
        response = await client.get('/v1/sessions/s1/stream')
        assert await response.content.readline() == b': keepalive\n'
        assert len(_events(app)) == before
        response.close()


def test_context_and_tools_persist_after_sse_retention_prunes_early_events(tmp_path, monkeypatch):
    from jaeger_ai.core.gateway import session_store as module
    monkeypatch.setattr(module, 'MAX_RETAINED_EVENTS', 4)
    store = GatewaySessionStore(tmp_path/'owned-retention.sqlite3')
    store.ensure_session('owned-history')
    store.admit_request('owned-history','Question',request_id='owned-context')
    documents = [{'id':'owned-doc','revision':1,'digest':'owned-digest','title':'Owned reference'}]
    store.append_event('owned-history','agent.knowledge',{'request_id':'owned-context','documents':documents})
    store.append_event('owned-history','tool.started',{'request_id':'owned-context','call_id':'owned-tool','tool':'read_file'})
    store.append_event('owned-history','tool.completed',{'request_id':'owned-context','call_id':'owned-tool','tool':'read_file','outcome':'completed'})
    for _ in range(8):
        store.append_event('owned-history','turn.delta',{'request_id':'owned-context','delta':'a'})
    assert not any(event['event']=='agent.knowledge' for event in store.replay_events('owned-history',0)['events'])
    store.complete_request('owned-context',status='completed',result={},assistant_text='aaaaaaaa')
    parts=store.get_session('owned-history')['messages'][-1]['parts']
    assert any(part['type']=='knowledge' and part['documents']==documents for part in parts)
    assert any(part['type']=='tool' and part['call_id']=='owned-tool' and part['status']=='completed' for part in parts)

def test_stream_extras_survive_completion_and_repeated_reload(tmp_path):
    gateway = _gateway(tmp_path)
    store = gateway.store
    store.admit_request("s1", "look up details", request_id="r1")
    for event, data in [
        ("turn.plan", {"plan": [{"step": "Research", "status": "in_progress"}]}),
        ("turn.progress", {"text": "Checking"}),
        ("turn.checkpoint", {"text": "Found a reference"}),
        ("tool.started", {"call_id": "c1", "tool": "web_search"}),
        ("tool.completed", {"call_id": "c1", "tool": "web_search"}),
        ("sources", {"sources": [{"kind": "url", "location": "https://example.com"}]}),
    ]:
        gateway.event_bus.publish("s1", event, {"request_id": "r1", **data})
    store.complete_request("r1", status="completed", result={"output": "Answer"},
                           assistant_text="Answer", follow_ups=["Explain more"])
    first = store.get_session("s1")["messages"][-1]["parts"]
    kinds = [part["type"] for part in first]
    assert all(kind in kinds for kind in ["plan", "progress", "checkpoint", "sources", "search_count", "follow_ups", "text"])
    assert next(part for part in first if part["type"] == "text")["text"] == "Answer"
    for _ in range(3):
        assert store.get_session("s1")["messages"][-1]["parts"] == first
    replay = store.complete_request("r1", status="completed", result={}, assistant_text="Do not duplicate")
    assert replay["replayed"] is True
    assert store.get_session("s1")["messages"][-1]["parts"] == first


def test_progress_notes_and_reasoning_are_durable_before_final_answer(tmp_path):
    from jaeger_ai.core.gateway.turn_parts import project_parts
    gateway = _gateway(tmp_path)
    callbacks, finish = gateway._turn_stream_callbacks('s1', 'notes-proof')
    callbacks.reasoning('Checking the available evidence.')
    callbacks.thinking('Retrying the model after a temporary connection failure.')
    # Events must already be durable while the turn is still running.
    events = _events(gateway)
    assert any(e['event'] == 'turn.reasoning' for e in events)
    note = next(e for e in events if e['event'] == 'turn.progress')
    assert note['data']['channel'] == 'status'
    assert note['data']['request_id'] == 'notes-proof'
    callbacks.stream_delta('Answer')
    finish()
    parts = project_parts(_events(gateway), 'Answer')
    assert [p['type'] for p in parts] == ['reasoning', 'progress', 'text']
    assert parts[0]['duration_ms'] >= 0
    assert parts[1]['message'].startswith('Retrying')
    assert sum(p.get('text') == 'Answer' for p in parts) == 1
