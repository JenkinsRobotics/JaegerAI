"""Failed tool results carry a structured recovery hint."""
from __future__ import annotations

from jaeger_agent.loop import jaeger_agent as ja


def test_generic_failure_asks_for_cause_and_a_change():
    hint = ja._recovery_hint("terminal", {"command": "make"}, "exit 2")
    assert "state the cause" in hint and "Do not repeat the identical call" in hint
    assert "Relative paths resolve" not in hint


def test_path_failure_names_where_paths_resolve(monkeypatch, tmp_path):
    from jaeger_agent.core import workspace as ws

    class L:
        root = tmp_path

    monkeypatch.setattr(ws, "writable_roots", lambda: [tmp_path / "workspace"])
    monkeypatch.setattr(ws, "get_project_root", lambda: None)
    monkeypatch.setattr(ws, "_require_layout", lambda: L())
    hint = ja._recovery_hint("read_file", {"path": "notes.txt"}, "No such file or directory: notes.txt")
    assert f"Relative paths resolve from {tmp_path}" in hint
    assert str(tmp_path / "workspace") in hint


def test_path_failure_without_a_bound_instance_still_guides(monkeypatch):
    from jaeger_agent.core import workspace as ws

    def boom():
        raise RuntimeError("unbound")

    monkeypatch.setattr(ws, "writable_roots", boom)
    hint = ja._recovery_hint("write_file", {"path": "/x"}, "path is outside the allowed roots")
    assert "Check what exists" in hint
