"""Specialists run the full agent loop with their own tool grant and notes."""
from types import SimpleNamespace

from jaeger_agent.tools.agent_notes import agent_notes, bound_notes_dir
from jaeger_ai.core.agent_registry.specialists import STANDING_SPECIALISTS, specialist_tools
from jaeger_ai.core.gateway.server import JaegerGatewayApp


def _agent(name, **meta):
    return SimpleNamespace(id="native:"+name,name=name, metadata=meta, role=SimpleNamespace(value="specialist"))


def test_every_standing_specialist_has_a_scoped_tool_set_with_its_notes_tool():
    for spec in STANDING_SPECIALISTS:
        tools = specialist_tools(_agent(spec["name"]))
        assert tools and "agent_notes" in tools
        assert not {"remember", "recall", "update_soul", "set_name", "set_autonomy"} & set(tools)
    assert specialist_tools(_agent("everyday", allowed_tools=["get_time"])) == ["get_time"]
    assert specialist_tools(_agent("unknown")) is None


def test_scope_intersects_with_the_admitted_grant(tmp_path, monkeypatch):
    monkeypatch.setattr(JaegerGatewayApp, "_instance_root", staticmethod(lambda: tmp_path))
    app = SimpleNamespace(agent_memory_dir=JaegerGatewayApp.agent_memory_dir)
    scope = JaegerGatewayApp._specialist_scope(app, _agent("everyday"), {"model": "m"})
    assert "get_events" in scope["execution"]["allowed_tools"] and scope["execution"]["model"] == "m"
    import hashlib
    assert scope["notes_dir"] == tmp_path / "memory" / "agents" / "by-id" / hashlib.sha256(b"native:everyday").hexdigest()[:32]
    composed = JaegerGatewayApp._specialist_scope(app, _agent("everyday"), {"allowed_tools": []})
    assert composed["execution"]["allowed_tools"] == []  # compose-only stays compose-only
    narrow = JaegerGatewayApp._specialist_scope(app, _agent("everyday"), {"allowed_tools": ["get_time", "terminal"]})
    assert narrow["execution"]["allowed_tools"] == ["get_time"]
    assert JaegerGatewayApp._specialist_scope(app, _agent("everyday"), None) is None


def test_agent_notes_only_touch_the_bound_agents_file(tmp_path):
    assert agent_notes("read")["ok"] is False  # not a specialist turn
    d = tmp_path / "everyday"
    with bound_notes_dir(d):
        assert agent_notes("append", "Prefers mornings.")["ok"]
        assert agent_notes("append", "Dentist on Tuesdays.")["ok"]
        assert agent_notes("read")["notes"] == "Prefers mornings.\nDentist on Tuesdays.\n"
        assert agent_notes("replace", "Mornings.")["ok"]
        assert agent_notes("delete")["ok"] is False
        assert agent_notes("append", "x" * 20000)["ok"] is False
    assert (d / "NOTES.md").read_text() == "Mornings.\n"
    assert agent_notes("read")["ok"] is False
