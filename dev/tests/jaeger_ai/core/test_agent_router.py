"""Lead triage suggests a specialist; it never moves a conversation by itself."""
from types import SimpleNamespace

from jaeger_ai.core.agent_registry.router import suggest_specialist
from jaeger_ai.core.gateway import session_hygiene as h
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def test_suggestions():
    assert suggest_specialist("what's on my calendar tomorrow?") == "native:everyday"
    assert suggest_specialist("the webui sidebar is broken") == "native:surfaces"
    assert suggest_specialist("approvals on the gateway hang") == "native:gateway"
    assert suggest_specialist("how are you?") is None
    assert suggest_specialist("email me about the gateway") is None  # tie: lead keeps it


def test_new_chats_belong_to_jaeger(tmp_path):
    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    chat = h.archive_on_create(store, store.ensure_session("c1", title="New Conversation"))
    assert chat["metadata"]["agent_id"] == "native:jaeger"
    own = h.archive_on_create(store, store.ensure_session("c2", metadata={"agent_id": "native:gateway"}))
    assert own["metadata"]["agent_id"] == "native:gateway"
    system = h.archive_on_create(store, store.ensure_session("heartbeat"))
    assert not (system.get("metadata") or {}).get("agent_id")
    rows = [{"session_id": "x", "title": "hey", "message_count": 2, "metadata": {}},
            {"session_id": "y", "title": "hey", "message_count": 2, "metadata": {"agent_id": "native:jaeger"}},
            {"session_id": "sota-1", "title": "hey", "message_count": 2, "metadata": {}}]
    assert h.unassigned_chats(rows) == ["x"]


def _app(store):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp

    events = []
    app = SimpleNamespace(store=store, event_bus=SimpleNamespace(publish=lambda *a: events.append(a)),
                          _registry=lambda: SimpleNamespace(get_agent=lambda aid: object()))
    app._session_agent_id = lambda s: JaegerGatewayApp._session_agent_id(app, s)
    return app, events, JaegerGatewayApp


def test_auto_route_hands_off_once_with_a_notice_and_never_overrides_the_owner(tmp_path):
    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    store.ensure_session("c1", metadata={"agent_id": "native:jaeger"})
    app, events, G = _app(store)
    assert G._auto_route(app, store.get_session("c1"), "check my calendar") is True
    meta = store.get_session("c1")["metadata"]
    assert meta["agent_id"] == "native:everyday" and meta["previous_agent_id"] == "native:jaeger"
    assert meta["routed_by"] == "auto" and events[-1][1] == "session.handoff"
    # Once per conversation.
    assert G._auto_route(app, store.get_session("c1"), "webui sidebar") is False
    # Owner-pinned and home sessions are never moved; no match stays with Jaeger.
    store.ensure_session("c2", metadata={"agent_id": "native:jaeger", "agent_pinned": True})
    store.ensure_session("c3", metadata={"agent_id": "native:jaeger", "home": True})
    store.ensure_session("c4", metadata={"agent_id": "native:jaeger"})
    assert not G._auto_route(app, store.get_session("c2"), "my calendar")
    assert not G._auto_route(app, store.get_session("c3"), "my calendar")
    assert not G._auto_route(app, store.get_session("c4"), "how are you")
    assert store.get_session("c4")["metadata"]["agent_id"] == "native:jaeger"


def test_specialist_sees_only_its_own_notes(tmp_path, monkeypatch):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp

    monkeypatch.setattr(JaegerGatewayApp, "_instance_root", staticmethod(lambda: tmp_path))
    ev = SimpleNamespace(id="native:everyday",role=SimpleNamespace(value="specialist"),display_name="Everyday",name="everyday",metadata={"specialty":"everyday"})
    gw = SimpleNamespace(id="native:gateway",name="gateway")
    d = JaegerGatewayApp.agent_memory_dir(ev); d.mkdir(parents=True)
    (d / "NOTES.md").write_text("Alice prefers mornings.")
    other = JaegerGatewayApp.agent_memory_dir(gw); other.mkdir(parents=True)
    (other / "NOTES.md").write_text("gateway secret plan")
    prompt = JaegerGatewayApp._system_prompt_for_agent(ev)
    assert "Alice prefers mornings." in prompt and "gateway secret plan" not in prompt
    assert JaegerGatewayApp.agent_memory_dir(ev)!=JaegerGatewayApp.agent_memory_dir(gw)
    assert JaegerGatewayApp.agent_memory_dir(ev).parent.name=="by-id"
