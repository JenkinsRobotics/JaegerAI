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
