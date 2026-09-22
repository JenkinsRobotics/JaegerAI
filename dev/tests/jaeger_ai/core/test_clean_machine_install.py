"""Workstream 24 — isolated-state first boot does not touch operator ~/.jaeger.

This is not a wiped macOS VM. It constructs a genuine isolated HOME /
JAEGER_STATE_DIR and proves clone-local imports, identity, and session
store creation do not open the operator state root.

Limitation (documented): the Python interpreter and venv still live at
~/.jaeger/venv. That is the development environment, not agent state.
"""
from __future__ import annotations

from pathlib import Path


def test_isolated_state_creates_identity_without_operator_home(tmp_path: Path, monkeypatch):
    isolated = tmp_path / "clean-machine"
    home = isolated / "home"
    state = isolated / "state"
    home.mkdir(parents=True)
    state.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(state))
    monkeypatch.setenv("JAEGER_HOME", str(state))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)

    from jaeger_ai.core.instance.instance import operator_state_root

    root = operator_state_root()
    assert Path(root) == state.resolve() or Path(root).is_relative_to(state)
    assert Path.home() == home
    assert Path.home() / ".jaeger" != Path(root)
    assert "GitHub/JaegerAI" not in str(root)

    from jaeger_ai.core.entity.identity import EntityIdentity
    from jaeger_ai.core.instance.instance import InstanceLayout

    inst = state / "instances" / "clean-boot"
    inst.mkdir(parents=True)
    layout = InstanceLayout(root=inst)
    identity = EntityIdentity.create_default(instance_name="clean-boot", display_name="Clean Jaeger")
    identity_path = inst / "memory" / "entity_identity.json"
    identity.save_to_file(identity_path)

    loaded = EntityIdentity.load_from_file(identity_path)
    assert loaded.entity_id == identity.entity_id
    assert loaded.display_name == "Clean Jaeger"
    assert state.resolve() in identity_path.resolve().parents
    assert layout.root == inst


def test_isolated_gateway_store_does_not_open_operator_sessions(tmp_path: Path, monkeypatch):
    state = tmp_path / "gw-iso"
    state.mkdir()
    monkeypatch.setenv("JAEGER_STATE_DIR", str(state))
    monkeypatch.setenv("JAEGER_HOME", str(state))

    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.instance.instance import operator_state_root

    db = operator_state_root() / "gateway_sessions.sqlite3"
    store = GatewaySessionStore(db)
    session = store.ensure_session("clean-boot-session", title="clean-boot")
    assert db.is_file()
    assert db.parent == Path(state).resolve() or db.is_relative_to(state)
    assert session["session_id"] == "clean-boot-session"
    listed = store.list_sessions()
    assert any(row["session_id"] == session["session_id"] for row in listed)


def test_clean_machine_limitations_are_documented():
    text = Path("docs/architecture/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "wiped Mac" in text or "wiped macOS" in text or "isolated state dir" in text.lower()
