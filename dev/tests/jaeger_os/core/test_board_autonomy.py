"""Kanban autonomy: digest, has-actionable, agent self-promotion.

The bug we're guarding against: the agent doesn't pick up its own
backlog because (a) the board isn't surfaced in the system prompt,
(b) the move tool used to refuse ``backlog → ready`` for an agent,
and (c) no idle trigger fired for board work — only Deep Think.

This file pins:
  * ``board_digest`` returns a compact, capped, priority-ordered
    summary suitable for prompt injection
  * ``has_actionable_work`` is True when any actionable column has
    a card, False otherwise
  * ``board_move`` lets the agent self-promote ``backlog → ready``
    (the old approval gate was removed)
  * the digest is empty when the board is quiet (so quiet instances
    don't pay any prompt cost)
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from jaeger_os.agent.background.board import (
    Board,
    board_digest,
    board_for_layout,
    has_actionable_work,
)


def _make_layout(tmp_path: Path) -> object:
    mem = tmp_path / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    return types.SimpleNamespace(root=tmp_path, memory_dir=mem)


def _board(tmp_path: Path) -> Board:
    return board_for_layout(_make_layout(tmp_path))


# ── digest ──────────────────────────────────────────────────────────


def test_digest_is_empty_when_board_is_empty(tmp_path):
    """A quiet instance must pay zero prompt-token cost for the board
    surfacing — an empty digest stays out of the assembled prompt."""
    assert board_digest(_make_layout(tmp_path)) == ""


def test_digest_is_empty_when_only_done_and_blocked(tmp_path):
    """Done and blocked columns are not actionable — the agent must
    not be nudged to revisit them."""
    b = _board(tmp_path)
    b.add("a finished card", column="done")
    b.add("a stuck card", column="blocked")
    assert board_digest(_make_layout(tmp_path)) == ""
    # has_actionable_work should agree.
    assert has_actionable_work(_make_layout(tmp_path)) is False


def test_digest_surfaces_in_progress_ready_and_backlog(tmp_path):
    """All three actionable columns get their own block, with the
    column-count badge for quick scanning."""
    b = _board(tmp_path)
    b.add("write release notes", column="in_progress")
    b.add("port skill to linux", column="ready")
    b.add("investigate kanban", column="backlog")
    out = board_digest(_make_layout(tmp_path))
    assert "BOARD STATUS" in out
    assert "in_progress (1)" in out
    assert "ready (1)" in out
    assert "backlog (1)" in out
    assert "write release notes" in out
    assert "port skill to linux" in out
    assert "investigate kanban" in out


def test_digest_caps_per_column_to_keep_prompt_small(tmp_path):
    """A runaway 50-card backlog must not blow the prompt budget —
    cap is 6 titles per column; the rest are summarized."""
    b = _board(tmp_path)
    for i in range(12):
        b.add(f"task number {i}", column="backlog")
    out = board_digest(_make_layout(tmp_path))
    # Six titles get inlined; the remaining six get the summary line.
    assert "task number 0" in out
    assert out.count("• card_") <= 6
    assert "and 6 more" in out


def test_digest_orders_by_priority_then_creation_time(tmp_path):
    """High-priority cards appear first within a column so the agent
    sees the most important work at the top of each block."""
    b = _board(tmp_path)
    b.add("low first", column="ready", priority="low")
    b.add("high later", column="ready", priority="high")
    b.add("med middle", column="ready", priority="med")
    out = board_digest(_make_layout(tmp_path))
    hi = out.index("high later")
    md = out.index("med middle")
    lo = out.index("low first")
    assert hi < md < lo


def test_digest_truncates_long_titles(tmp_path):
    """A 200-character title would dominate the digest. Truncate to
    keep one card from squeezing out the rest."""
    b = _board(tmp_path)
    b.add("x" * 300, column="ready")
    out = board_digest(_make_layout(tmp_path))
    # Long title got an ellipsis somewhere in its rendering.
    assert "…" in out


# ── has_actionable_work ─────────────────────────────────────────────


def test_has_actionable_work_true_for_in_progress(tmp_path):
    b = _board(tmp_path)
    b.add("doing it", column="in_progress")
    assert has_actionable_work(_make_layout(tmp_path)) is True


def test_has_actionable_work_true_for_ready(tmp_path):
    b = _board(tmp_path)
    b.add("up next", column="ready")
    assert has_actionable_work(_make_layout(tmp_path)) is True


def test_has_actionable_work_true_for_backlog(tmp_path):
    """Backlog counts as actionable under the new autonomous-pickup
    model — agent will self-promote when it has free time."""
    b = _board(tmp_path)
    b.add("proposal", column="backlog")
    assert has_actionable_work(_make_layout(tmp_path)) is True


def test_has_actionable_work_false_for_only_done(tmp_path):
    b = _board(tmp_path)
    b.add("finished", column="done")
    assert has_actionable_work(_make_layout(tmp_path)) is False


def test_has_actionable_work_false_for_only_blocked(tmp_path):
    """Blocked needs the USER — the agent shouldn't take initiative
    on those (it would just block on the same thing again)."""
    b = _board(tmp_path)
    b.add("waiting on user", column="blocked")
    assert has_actionable_work(_make_layout(tmp_path)) is False


# ── move-gate removal ──────────────────────────────────────────────


# ── card kinds (general vs deepthink) ─────────────────────────────


def test_board_add_default_kind_is_general(tmp_path, monkeypatch):
    """Default ``kind="general"`` lands the card in ``ready`` with
    source=agent — worked by the current loaded model when the idle
    worker fires."""
    layout = _make_layout(tmp_path)
    import jaeger_os.agent.tools.board as board_tool
    monkeypatch.setattr(board_tool, "_require_layout", lambda: layout)

    out = board_tool.board_add("write a haiku")
    assert out["ok"] is True
    assert out["kind"] == "general"
    assert out["column"] == "ready"
    assert out["source"] == "agent"


def test_board_add_deepthink_lands_in_backlog_with_deepthink_source(
        tmp_path, monkeypatch):
    """``kind="deepthink"`` lands in ``backlog`` with source=deepthink
    so the user must approve the model swap before it fires. Once
    moved to ``ready``, the idle-tick Deep Think worker picks it up
    (model swap to the coder model) instead of the general worker."""
    layout = _make_layout(tmp_path)
    import jaeger_os.agent.tools.board as board_tool
    monkeypatch.setattr(board_tool, "_require_layout", lambda: layout)

    out = board_tool.board_add("port the macOS skill", kind="deepthink")
    assert out["ok"] is True
    assert out["kind"] == "deepthink"
    assert out["column"] == "backlog"
    assert out["source"] == "deepthink"


def test_board_add_rejects_unknown_kind(tmp_path, monkeypatch):
    """A typo'd kind ('deepthought') must fail loudly, not silently
    fall back to general — otherwise the user's intent to invoke the
    coder model would be lost."""
    layout = _make_layout(tmp_path)
    import jaeger_os.agent.tools.board as board_tool
    monkeypatch.setattr(board_tool, "_require_layout", lambda: layout)

    out = board_tool.board_add("x", kind="deepthought")
    assert out["ok"] is False
    assert "deepthought" in out["error"]


def test_kanban_action_dispatch_passes_kind_through(tmp_path, monkeypatch):
    """The unified ``kanban(action="add", kind="deepthink", ...)`` API
    must forward ``kind`` to board_add — otherwise a model that only
    calls the umbrella tool can't create deep-think cards."""
    layout = _make_layout(tmp_path)
    import jaeger_os.agent.tools.board as board_tool
    monkeypatch.setattr(board_tool, "_require_layout", lambda: layout)

    out = board_tool.kanban(action="add", title="hard task",
                            kind="deepthink")
    assert out["ok"] is True
    assert out["kind"] == "deepthink"
    assert out["column"] == "backlog"


def test_board_move_now_allows_backlog_to_ready(tmp_path, monkeypatch):
    """The old ``backlog → ready was user-only`` gate is gone — the
    agent self-promotes to keep its own queue moving when idle."""
    layout = _make_layout(tmp_path)
    # Patch the tool module's _require_layout import so board_move
    # picks up the tmp_path layout without rebinding the whole tools
    # package (bind() expects an InstanceLayout; ours is a stub).
    import jaeger_os.agent.tools.board as board_tool
    monkeypatch.setattr(board_tool, "_require_layout", lambda: layout)

    b = board_for_layout(layout)
    card = b.add("self-promote me", column="backlog")

    out = board_tool.board_move(card_id=card.id, column="ready")
    assert out["ok"] is True
    assert out["column"] == "ready"
    # And the board agrees on disk.
    refreshed = b.get(card.id)
    assert refreshed.column == "ready"
