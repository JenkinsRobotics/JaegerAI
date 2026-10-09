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


def test_memory_bind_ignores_a_stand_in_layout(tmp_path, monkeypatch):
    """A MagicMock layout bound in one test made later tool_calls writes
    create '<MagicMock ...memory_dir...>' SQLite files in the repo root."""
    from unittest.mock import MagicMock

    from jaeger_agent.memory import memory, sqlite_store

    monkeypatch.chdir(tmp_path)
    before = dict(sqlite_store._state)
    memory.bind(MagicMock())
    assert sqlite_store._state == before
    assert list(tmp_path.iterdir()) == []


def test_execute_code_path_failure_points_at_tools_that_see_the_workspace(monkeypatch, tmp_path):
    from jaeger_agent.core import workspace as ws
    from jaeger_agent.loop.jaeger_agent import _recovery_hint, _stderr_tail

    monkeypatch.setattr(ws, "get_project_root", lambda: None)
    layout = type("L", (), {"root": tmp_path, "skills_dir": tmp_path / "skills"})()
    monkeypatch.setattr(ws, "_require_layout", lambda: layout)
    err = _stderr_tail({"ok": False, "stderr": "Traceback (most recent call last):\n  ...\n"
                        "FileNotFoundError: [Errno 2] No such file or directory: 'workspace/x/a.csv'\n"})
    assert err.startswith("FileNotFoundError")
    hint = _recovery_hint("execute_code", {"code": "open('workspace/x/a.csv')"}, err)
    assert "cannot see workspace files" in hint
    assert str(tmp_path / "skills") in hint and "read_file" in hint and "write_file" in hint
    assert f"terminal tool (starts in {tmp_path}" in hint


def test_execute_code_non_path_failure_gets_only_the_generic_hint():
    from jaeger_agent.loop.jaeger_agent import _recovery_hint

    hint = _recovery_hint("execute_code", {"code": "1/0"}, "ZeroDivisionError: division by zero")
    assert "cannot see workspace files" not in hint and "Do not repeat" in hint
