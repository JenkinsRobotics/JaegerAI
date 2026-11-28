"""Standalone tests for jaeger-memory."""

from __future__ import annotations

from pathlib import Path

from jaeger_contracts import StateMemoryPort
from jaeger_memory import (
    GitCheckpointManager,
    SqliteStateMemory,
    close_dangling_tool_calls,
)


def test_sqlite_state_memory_checkpoints_facts_and_tiered_compaction(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    mem = SqliteStateMemory(state_dir, max_inline_tool_chars=200)
    assert isinstance(mem, StateMemoryPort)

    cp = mem.save_checkpoint("s1", {"step": 3, "goal": "fix build"})
    assert mem.load_checkpoint(cp) == {"step": 3, "goal": "fix build"}
    assert mem.latest_checkpoint("s1") == {"step": 3, "goal": "fix build"}

    mem.remember("preferred_lang", "python", subject="owner")
    assert mem.recall("preferred_lang", subject="owner") == "python"

    # Tier 1 compaction offloads huge old tool output to disk with grep-able file
    big_log = "\n".join(f"line {i}: {'ERROR_BOOM' if i == 50 else 'ok'}" for i in range(200))
    msgs = [
        {"role": "system", "content": "You are Jaeger."},
        {"role": "user", "content": "Run tests"},
        {"role": "tool", "name": "shell", "tool_call_id": "tc1", "content": big_log},
        {"role": "assistant", "content": "Checking..."},
        {"role": "user", "content": "Fix it"},
    ]
    compacted = mem.compact(msgs, max_tokens=600)
    assert "[OFFLOADED" in compacted[2]["content"]
    offload_files = list((state_dir / "offload").glob("*.txt"))
    assert len(offload_files) == 1
    matches = mem.offloader.grep(offload_files[0].name, "ERROR_BOOM")
    assert matches == ["L51: line 50: ERROR_BOOM"]

    # Dangling tool call closure (ag2 invariant)
    dangling = [{"role": "assistant", "tool_calls": [{"id": "orphan_1", "name": "shell"}]}]
    closed = close_dangling_tool_calls(dangling)
    assert len(closed) == 2 and closed[1]["tool_call_id"] == "orphan_1"


def test_git_checkpoint_manager_snapshot_and_restore(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    target = ws / "app.py"
    target.write_text("v1\n", encoding="utf-8")

    mgr = GitCheckpointManager(ws, tmp_path / "state")
    snap = mgr.snapshot()
    target.write_text("BROKEN_V2\n", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "BROKEN_V2\n"

    mgr.restore(snap)
    assert target.read_text(encoding="utf-8") == "v1\n"


def test_offloader_grep_searches_extra_tool_results_dirs_and_clips_single_line_json(tmp_path: Path) -> None:
    import pytest
    from jaeger_memory import ToolOutputOffloader

    state_dir = tmp_path / "state"
    tool_results = tmp_path / "instances" / "truth" / "logs" / "tool_results"
    tool_results.mkdir(parents=True)
    artifact = tool_results / "20261124-114442_547c2685.json"
    huge_json = '{"pad": "' + ("x" * 2000) + '", "account": "Google", "tail": "' + ("y" * 2000) + '"}'
    artifact.write_text(huge_json, encoding="utf-8")

    offloader = ToolOutputOffloader(state_dir, extra_dirs=(tool_results,))
    by_abs = offloader.grep(str(artifact), '"account": "Google"')
    by_name = offloader.grep(artifact.name, '"account": "Google"')
    assert len(by_abs) == 1 and '"account": "Google"' in by_abs[0]
    assert len(by_abs[0]) < 600  # clipped window, not full 4KB single line
    assert by_name == by_abs

    outside = tmp_path / "secret.txt"
    outside.write_text("Google", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        offloader.grep(str(outside), "Google")


def test_history_replayable_span_and_orphan_preserving_boundary() -> None:
    from jaeger_memory import choose_boundary, replayable_span, snap

    msgs = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "tool_calls": [{"id": "c1", "name": "read"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "tool_calls": [{"id": "c2", "name": "edit"}]},
        {"role": "tool", "tool_call_id": "c2", "content": "r2"},
    ]
    # Cutting right on the tool result at index 2 must snap backward to index 1
    assert snap(msgs, 2) == 1
    span = replayable_span(msgs, 2)
    assert span[0]["role"] == "assistant"
    assert span[1]["tool_call_id"] == "c1"

    # Cutting with keep_recent=1 lands on tool result c2 -> must expand to include assistant c2
    older, recent = choose_boundary(msgs, keep_recent=1)
    assert recent[0]["role"] == "assistant"
    assert recent[1]["tool_call_id"] == "c2"
    assert len(older) + len(recent) == len(msgs)


def test_wal_checkpoint_writes_and_redos_safe_grep(tmp_path: Path) -> None:
    import pytest
    from jaeger_memory import RegexTimeoutError, ToolOutputOffloader, deterministic_resource_id

    mem = SqliteStateMemory(tmp_path / "wal_state")
    cp_id = mem.save_checkpoint("sess-1", {"step": 1, "notes": []})
    mem.put_writes(cp_id, "task-a", [("step", 2), ("status", "running")])
    mem.put_writes(cp_id, "task-b", [("summary", "ok")])
    writes = mem.get_writes(cp_id)
    assert len(writes) == 3
    merged = mem.load_checkpoint_with_writes(cp_id)
    assert merged == {"step": 2, "notes": [], "status": "running", "summary": "ok"}

    # Deterministic res_ ID + lookup by res_ ID
    offloader = ToolOutputOffloader(tmp_path / "wal_state", max_inline_chars=128)
    body = "a" * 35 + "!\n" + ("hello world\n" * 20)
    env, path = offloader.maybe_offload("shell", body)
    res_id = deterministic_resource_id("shell", body)
    assert path is not None and res_id in env
    assert offloader.grep(res_id, "hello world", max_matches=2)

    # Catastrophic backtracking regex must raise RegexTimeoutError, never hang
    with pytest.raises(RegexTimeoutError):
        offloader.grep(res_id, r"(a+)+$", timeout_s=0.3)

