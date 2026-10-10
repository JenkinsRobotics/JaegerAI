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


def test_gateway_records_the_suggestion_once_and_keeps_the_lead(tmp_path):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp

    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    store.ensure_session("c1", metadata={"agent_id": "native:jaeger"})
    app = SimpleNamespace(store=store)
    lead = SimpleNamespace(role=SimpleNamespace(value="lead"))
    JaegerGatewayApp._suggest_route(app, store.get_session("c1"), lead, "check my calendar")
    meta = store.get_session("c1")["metadata"]
    assert meta["suggested_agent_id"] == "native:everyday" and meta["agent_id"] == "native:jaeger"
    JaegerGatewayApp._suggest_route(app, store.get_session("c1"), lead, "webui sidebar")
    assert store.get_session("c1")["metadata"]["suggested_agent_id"] == "native:everyday"


def test_specialist_sees_only_its_own_notes(tmp_path, monkeypatch):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp

    monkeypatch.setattr(JaegerGatewayApp, "_instance_root", staticmethod(lambda: tmp_path))
    d = JaegerGatewayApp.agent_memory_dir("everyday"); d.mkdir(parents=True)
    (d / "NOTES.md").write_text("Matthew prefers mornings.")
    other = JaegerGatewayApp.agent_memory_dir("gateway"); other.mkdir(parents=True)
    (other / "NOTES.md").write_text("gateway secret plan")
    ev = SimpleNamespace(role=SimpleNamespace(value="specialist"), display_name="Everyday", name="everyday",
                         metadata={"specialty": "everyday"})
    prompt = JaegerGatewayApp._system_prompt_for_agent(ev)
    assert "Matthew prefers mornings." in prompt and "gateway secret plan" not in prompt
    assert JaegerGatewayApp.agent_memory_dir("../x").name == "___x"
