"""Tests for SQLite WAL KanbanBoard & OneShotReminderStore (JROS patterns)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_orchestration import KanbanBoard, OneShotReminderStore


def test_kanban_board_crud_and_markdown(tmp_path: Path) -> None:
    board = KanbanBoard(tmp_path / "board.sqlite3")
    c1 = board.create_card("Calibrate JP01 neck servo", column="todo", priority=1, tags=["jp01", "hardware"])
    c2 = board.create_card("Record YouTube demo", column="backlog", priority=2)

    moved = board.move_card(c1.card_id, "in_progress", notes="Testing torque limits")
    assert moved.column == "in_progress" and moved.notes == "Testing torque limits"

    summary = board.summary()
    assert summary["total"] == 2
    assert summary["counts"]["in_progress"] == 1
    assert summary["counts"]["backlog"] == 1

    md = board.render_markdown()
    assert "# Jaeger Task Board" in md and "Calibrate JP01 neck servo" in md

    assert board.delete_card(c2.card_id) is True
    assert board.summary()["total"] == 1


def test_oneshot_reminder_in_minutes_and_due_claim(tmp_path: Path) -> None:
    store = OneShotReminderStore(tmp_path / "rem.sqlite3")
    r1 = store.schedule("Check 3D printer bed", in_minutes=10, now=1000.0)
    r2 = store.schedule("Cancel me", in_minutes=30, now=1000.0)
    assert r1.due_at == pytest.approx(1600.0)

    assert store.cancel(r2.reminder_id) is True
    assert len(store.list_reminders(status="pending")) == 1

    # Not due yet at 1500.0; fires atomically once at 1605.0
    assert store.claim_due(now=1500.0) == []
    fired = store.claim_due(now=1605.0)
    assert len(fired) == 1 and fired[0].reminder_id == r1.reminder_id and fired[0].status == "fired"
    assert store.claim_due(now=1700.0) == []
