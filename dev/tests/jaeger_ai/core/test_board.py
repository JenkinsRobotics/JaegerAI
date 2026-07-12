"""Kanban board — model, tools, and the Deep Think view over it.

The board (docs/kanban_design.md) is the agent's unified task surface.
Deep Think is no longer a separate queue file — a Deep Think job is a
board card with ``source="deepthink"``, and ``DeepThinkQueue`` is a thin
view over the board that keeps its original API.
"""

from __future__ import annotations

import pytest

from jaeger_ai.agent import tools
from jaeger_ai.agent.background.board import Board, board_for_layout
from jaeger_ai.agent.background.deep_think import queue_for_layout
from jaeger_ai.core.instance.instance import InstanceLayout


@pytest.fixture()
def bound_instance(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    return layout


# ── Board model ──────────────────────────────────────────────────────


def test_board_add_get_list(bound_instance):
    board = board_for_layout(bound_instance)
    card = board.add("write the readme")
    assert card.column == "backlog"
    assert board.get(card.id).title == "write the readme"
    assert len(board.list()) == 1


def test_board_move_stamps_timestamps(bound_instance):
    board = board_for_layout(bound_instance)
    card = board.add("a task", column="ready")
    board.move(card.id, "in_progress")
    assert board.get(card.id).started_at is not None
    board.move(card.id, "done")
    assert board.get(card.id).finished_at is not None


def test_board_update_and_summary(bound_instance):
    board = board_for_layout(bound_instance)
    c = board.add("x")
    board.update(c.id, notes="started looking")
    assert board.get(c.id).notes == "started looking"
    board.add("y", column="done")
    summary = board.summary()
    assert summary["total"] == 2 and summary["done"] == 1


def test_board_persists_across_instances(bound_instance):
    board_for_layout(bound_instance).add("persisted")
    # A fresh Board over the same path sees it.
    assert len(board_for_layout(bound_instance).list()) == 1


# ── Board tools ──────────────────────────────────────────────────────


def test_board_add_tool_lands_in_ready(bound_instance):
    result = tools.board_add("ship 0.1.0")
    assert result["ok"] is True
    assert result["column"] == "ready"


def test_board_move_tool_allows_agent_self_promotion(bound_instance):
    """The old ``backlog → ready was user-only`` gate was removed when
    the agent gained autonomous backlog pickup — the whole board is
    actionable work and the agent self-promotes as part of normal
    operation. The user still owns the board via ``/board``."""
    board = board_for_layout(bound_instance)
    card = board.add("proposed work", column="backlog")
    result = tools.board_move(card.id, "ready")
    assert result["ok"] is True
    assert result["column"] == "ready"


def test_board_move_tool_allows_normal_moves(bound_instance):
    card = board_for_layout(bound_instance).add("task", column="ready")
    assert tools.board_move(card.id, "in_progress")["ok"] is True
    assert tools.board_move(card.id, "done")["ok"] is True


def test_board_view_tool(bound_instance):
    tools.board_add("one")
    tools.board_add("two")
    result = tools.board_view()
    assert result["ok"] is True
    assert result["summary"]["total"] == 2


# ── Deep Think as a view over the board ──────────────────────────────


def test_deepthink_user_task_is_ready(bound_instance):
    queue = queue_for_layout(bound_instance)
    task = queue.add("build a weather skill", source="user")
    assert task.approved is True
    assert queue.next_pending().id == task.id


def test_deepthink_agent_task_needs_approval(bound_instance):
    queue = queue_for_layout(bound_instance)
    task = queue.add("refactor the parser", source="agent")
    assert task.approved is False
    assert queue.next_pending() is None  # not eligible until approved
    queue.approve(task.id)
    assert queue.next_pending().id == task.id


def test_deepthink_tasks_show_on_the_board(bound_instance):
    """A Deep Think job and an ad-hoc card share one board."""
    queue_for_layout(bound_instance).add("deepthink job", source="user")
    tools.board_add("ad-hoc card")
    board = board_for_layout(bound_instance)
    assert board.summary()["total"] == 2
    deepthink_cards = board.list(tag="deepthink")
    assert len(deepthink_cards) == 1


def test_deepthink_mark_done_and_summary(bound_instance):
    queue = queue_for_layout(bound_instance)
    task = queue.add("a job", source="user")
    queue.mark_in_progress(task.id)
    assert queue.get(task.id).status == "in_progress"
    queue.mark_done(task.id, result="shipped")
    assert queue.get(task.id).status == "done"
    assert queue.summary()["done"] == 1


def test_deepthink_legacy_queue_migrates(bound_instance):
    """A pre-board deep_think_queue.jsonl is folded into the board once."""
    import json

    legacy = bound_instance.memory_dir / "deep_think_queue.jsonl"
    legacy.write_text(
        json.dumps({"description": "old task", "source": "user",
                    "status": "pending", "approved": True}) + "\n",
        encoding="utf-8",
    )
    queue = queue_for_layout(bound_instance)
    tasks = queue.all_tasks()
    assert len(tasks) == 1 and tasks[0].description == "old task"
    assert not legacy.exists()  # renamed aside after migrating
