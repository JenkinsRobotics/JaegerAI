"""The in-session `todo` planning tool.

A scratchpad task list so a small model keeps the thread on a
multi-step job — write a plan, work it one item at a time, stop when
every item is done.
"""

from __future__ import annotations

from jaeger_os.agent.tools.todo import TodoStore, reset_todos, todo


# ── TodoStore ───────────────────────────────────────────────────────


def test_write_replace_then_read() -> None:
    s = TodoStore()
    s.write([{"id": "1", "content": "a", "status": "pending"},
             {"id": "2", "content": "b", "status": "in_progress"}])
    items = s.read()
    assert [i["id"] for i in items] == ["1", "2"]
    assert items[1]["status"] == "in_progress"


def test_write_replace_drops_old_items() -> None:
    s = TodoStore()
    s.write([{"id": "1", "content": "a", "status": "pending"}])
    s.write([{"id": "9", "content": "z", "status": "pending"}])
    assert [i["id"] for i in s.read()] == ["9"]


def test_merge_updates_by_id_and_appends() -> None:
    s = TodoStore()
    s.write([{"id": "1", "content": "a", "status": "pending"}])
    s.write([{"id": "1", "content": "a", "status": "completed"},
             {"id": "2", "content": "b", "status": "pending"}], merge=True)
    by = {i["id"]: i for i in s.read()}
    assert by["1"]["status"] == "completed"
    assert by["2"]["content"] == "b"


def test_invalid_status_coerced_to_pending() -> None:
    s = TodoStore()
    s.write([{"id": "1", "content": "a", "status": "bogus"}])
    assert s.read()[0]["status"] == "pending"


def test_duplicate_ids_deduped_last_wins() -> None:
    s = TodoStore()
    s.write([{"id": "1", "content": "first", "status": "pending"},
             {"id": "1", "content": "second", "status": "pending"}])
    items = s.read()
    assert len(items) == 1 and items[0]["content"] == "second"


# ── the todo() tool entry point ─────────────────────────────────────


def test_todo_tool_returns_summary_counts() -> None:
    reset_todos()
    out = todo([{"id": "1", "content": "a", "status": "pending"},
                {"id": "2", "content": "b", "status": "completed"}])
    assert out["ok"] is True
    assert out["summary"] == {"total": 2, "pending": 1, "in_progress": 0,
                              "completed": 1, "cancelled": 0}


def test_todo_tool_read_after_write() -> None:
    reset_todos()
    todo([{"id": "1", "content": "a", "status": "pending"}])
    assert len(todo()["todos"]) == 1  # read with no args


def test_reset_clears_the_list() -> None:
    todo([{"id": "x", "content": "y", "status": "pending"}])
    reset_todos()
    assert todo()["todos"] == []
