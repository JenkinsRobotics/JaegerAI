"""Session search reads only Jaeger's own stores: the Gateway database, the
agent state databases and per-profile stores. The OpenClaw JSONL reader was
retired on 2026-11-17."""
from __future__ import annotations

from jaeger_ai.features.session_search import endpoints as ep


def test_endpoints_are_the_three_jaeger_stores(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "agent"))
    names = [e.name for e in ep.endpoints()]
    assert names == ["gateway", "hermes", "webui-home"]
    assert ep.endpoints()[0].path == tmp_path / "gateway_sessions.sqlite3"
    assert not hasattr(ep, "_openclaw_endpoints")


def test_profile_store_adds_an_endpoint_named_for_its_folder(monkeypatch, tmp_path):
    home = tmp_path / "agent"
    (home / "profiles" / "coder").mkdir(parents=True)
    (home / "profiles" / "coder" / "state.db").write_bytes(b"")
    (home / "profiles" / "empty").mkdir()
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    extra = [e for e in ep.endpoints() if e.name.startswith("profile:")]
    assert [e.name for e in extra] == ["profile:coder"]
    assert extra[0].default_runtime == "coder"


def test_missing_stores_yield_no_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "agent"))
    assert ep.all_sessions() == []
