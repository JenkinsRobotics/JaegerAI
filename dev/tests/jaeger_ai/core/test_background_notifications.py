"""Background-process completion notifications.

The bug we're guarding against: a background task started via
``start_background`` finishes silently — the agent doesn't notice
until it polls ``check_background``. That breaks the use case the
tool exists for (long-running work that the agent should react to
when it ends).

This file pins the at-most-once notification queue: when a process
transitions to a terminal state, ``consume_pending_completions``
returns it exactly one time, then forgets about it.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

from jaeger_ai.agent.background import processes as proc


def _make_layout(tmp_path: Path) -> object:
    """Minimal duck-typed layout — only ``.root`` is touched here."""
    return types.SimpleNamespace(root=tmp_path)


def _write_proc(tmp_path: Path, *, process_id: str, status: str,
                notified: bool, name: str = "test") -> Path:
    proc_dir = tmp_path / "processes" / process_id
    proc_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "process_id": process_id,
        "name": name,
        "pid": 1,  # _pid_alive(1) is True on every Unix — we override below
        "status": status,
        "started_at": 0,
        "finished_at": 1.0 if status != "running" else None,
        "exit_code": 0 if status != "running" else None,
        "notified": notified,
    }
    (proc_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return proc_dir


def test_pending_completions_returns_unsurfaced_exits(tmp_path):
    """An exited process with ``notified=False`` shows up in the queue."""
    layout = _make_layout(tmp_path)
    _write_proc(tmp_path, process_id="proc_a", status="exited", notified=False)
    out = proc.consume_pending_completions(layout)
    assert len(out) == 1
    assert out[0]["process_id"] == "proc_a"
    assert out[0]["status"] == "exited"


def test_pending_completions_is_at_most_once(tmp_path):
    """Once surfaced, a completion does not appear again on the next call."""
    layout = _make_layout(tmp_path)
    _write_proc(tmp_path, process_id="proc_b", status="exited", notified=False)
    first = proc.consume_pending_completions(layout)
    second = proc.consume_pending_completions(layout)
    assert len(first) == 1
    assert second == []


def test_pending_completions_skips_already_notified(tmp_path):
    """A completion marked ``notified=True`` (e.g. user-initiated stop)
    must NOT be surfaced — the agent already knows."""
    layout = _make_layout(tmp_path)
    _write_proc(tmp_path, process_id="proc_c", status="stopped", notified=True)
    out = proc.consume_pending_completions(layout)
    assert out == []


def test_pending_completions_returns_each_distinct_completion(tmp_path):
    """Two unsurfaced completions — both appear, both get marked notified."""
    layout = _make_layout(tmp_path)
    _write_proc(tmp_path, process_id="proc_d", status="exited", notified=False)
    _write_proc(tmp_path, process_id="proc_e", status="exited", notified=False)
    out = proc.consume_pending_completions(layout)
    ids = {c["process_id"] for c in out}
    assert ids == {"proc_d", "proc_e"}
    # Second drain — both already surfaced.
    assert proc.consume_pending_completions(layout) == []


def test_pending_completions_empty_when_no_processes_dir(tmp_path):
    """A fresh instance with no background processes yet — empty queue,
    no crash."""
    layout = _make_layout(tmp_path)
    assert proc.consume_pending_completions(layout) == []
