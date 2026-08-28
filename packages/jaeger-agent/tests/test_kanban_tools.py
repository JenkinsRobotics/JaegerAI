"""Kanban worker/orchestrator tools.

Ported from hermes-agent ``tools/kanban_tools.py``. These tests cover the
coordination protocol Jaeger's kanban-orchestrator / kanban-worker skills
already instruct the model to use, plus the two invariants the donor treats
as load-bearing: the tools stay off an ordinary chat turn's schema, and a
delegate_task child may not mutate the board.
"""

from __future__ import annotations

import pytest

from jaeger_agent.background.board import Board
from jaeger_agent.delegation_context import delegated_child
from jaeger_agent.skill_registry import toolset_scoping as ts
from jaeger_agent.tools import kanban as k


@pytest.fixture()
def board(tmp_path, monkeypatch):
    """A bound instance whose board lives under tmp_path."""
    from jaeger_ai.core.instance.instance import InstanceLayout

    layout = InstanceLayout(root=tmp_path)
    layout.memory_dir.mkdir(parents=True, exist_ok=True)
    layout.skills_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("jaeger_agent.workspace.get_layout", lambda: layout)
    b = Board(layout.memory_dir / "board.json")
    # Dispatched-worker mode so the tools are live for the test.
    monkeypatch.setenv("JAEGER_KANBAN_TASK", "")
    ts.reset_toolsets()
    ts.enable_toolset("kanban")
    yield b
    ts.reset_toolsets()


def _card(board, title="task", **kw):
    return board.add(title, **kw)


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

def test_hidden_from_a_normal_chat_turn(board, monkeypatch):
    monkeypatch.delenv("JAEGER_KANBAN_TASK", raising=False)
    ts.reset_toolsets()
    assert k._kanban_mode() is False


def test_available_to_a_dispatched_worker(board, monkeypatch):
    monkeypatch.delenv("JAEGER_KANBAN_TASK", raising=False)
    ts.reset_toolsets()
    monkeypatch.setenv("JAEGER_KANBAN_TASK", "card_abc")
    assert k._kanban_mode() is True


def test_available_when_toolset_explicitly_loaded(board):
    assert k._kanban_mode() is True  # fixture loaded it


def test_all_fourteen_verbs_are_classified():
    """A tool in no toolset fails open — these must never be visible by
    accident, so the classification is part of the contract."""
    assert len(ts.TOOLSETS["kanban"]) == 14
    assert set(k.__all__) == ts.TOOLSETS["kanban"]


# ---------------------------------------------------------------------------
# Delegated children may not mutate
# ---------------------------------------------------------------------------

def test_delegated_child_cannot_complete(board):
    c = _card(board)
    with delegated_child():
        out = k.kanban_complete(c.id, "done")
    assert out["ok"] is False
    assert "not board run owners" in out["error"]
    assert board.get(c.id).column == "backlog"


def test_delegated_child_can_still_read(board):
    c = _card(board)
    with delegated_child():
        assert k.kanban_show(c.id)["ok"] is True
        assert k.kanban_list()["ok"] is True


@pytest.mark.parametrize("call", [
    lambda cid: k.kanban_complete(cid),
    lambda cid: k.kanban_block(cid, "why"),
    lambda cid: k.kanban_unblock(cid),
    lambda cid: k.kanban_heartbeat(cid),
    lambda cid: k.kanban_comment("hi", cid),
    lambda cid: k.kanban_request_review(cid),
    lambda cid: k.kanban_request_changes("fix", cid),
    lambda cid: k.kanban_attach_url("https://x.test", cid),
    lambda cid: k.kanban_create("new"),
    lambda cid: k.kanban_link(cid, cid),
])
def test_every_mutation_is_refused_for_children(board, call):
    c = _card(board)
    with delegated_child():
        out = call(c.id)
    assert out["ok"] is False
    assert "refused" in out["error"]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_create_and_show(board):
    out = k.kanban_create("build the thing", body="details", assignee="w1",
                          tags=["x"], priority="high")
    assert out["ok"] is True
    shown = k.kanban_show(out["id"])
    assert shown["title"] == "build the thing"
    assert shown["description"] == "details"
    assert shown["assignee"] == "w1"


def test_create_requires_a_title(board):
    assert k.kanban_create("   ")["ok"] is False


def test_complete_records_the_summary(board):
    c = _card(board)
    out = k.kanban_complete(c.id, "shipped it")
    assert out["column"] == "done"
    assert board.get(c.id).result == "shipped it"


def test_block_requires_a_reason(board):
    c = _card(board)
    out = k.kanban_block(c.id, "")
    assert out["ok"] is False
    assert "reason is required" in out["error"]
    assert board.get(c.id).column == "backlog"


def test_block_then_unblock(board):
    c = _card(board)
    k.kanban_block(c.id, "waiting on infra", kind="dependency")
    parked = board.get(c.id)
    assert parked.column == "blocked"
    assert parked.block_kind == "dependency"

    k.kanban_unblock(c.id)
    freed = board.get(c.id)
    assert freed.column == "ready"
    assert freed.block_reason == ""


def test_heartbeat_stamps_liveness(board):
    c = _card(board)
    assert board.get(c.id).heartbeat_at is None
    k.kanban_heartbeat(c.id, note="still going")
    assert board.get(c.id).heartbeat_at is not None
    assert board.get(c.id).notes == "still going"


def test_comments_append(board):
    c = _card(board)
    k.kanban_comment("first", c.id)
    k.kanban_comment("second", c.id)
    shown = k.kanban_show(c.id)
    assert [x["body"] for x in shown["comments"]] == ["first", "second"]


def test_comment_requires_a_body(board):
    c = _card(board)
    assert k.kanban_comment("  ", c.id)["ok"] is False


# ---------------------------------------------------------------------------
# Review handshake
# ---------------------------------------------------------------------------

def test_request_review_then_changes_reopens_the_card(board):
    c = _card(board)
    k.kanban_complete(c.id, "done")
    k.kanban_request_review(c.id, summary="please check", reviewer="lead")
    assert board.get(c.id).review_state == "requested"

    out = k.kanban_request_changes("missing tests", c.id)
    reopened = board.get(c.id)
    assert out["ok"] is True
    assert reopened.review_state == "changes_requested"
    assert reopened.review_feedback == "missing tests"
    # A card awaiting rework is not done.
    assert reopened.column == "in_progress"
    assert reopened.finished_at is None


def test_request_changes_requires_a_reason(board):
    c = _card(board)
    assert k.kanban_request_changes("", c.id)["ok"] is False


# ---------------------------------------------------------------------------
# Links and cycles
# ---------------------------------------------------------------------------

def test_link_records_dependency(board):
    a, b = _card(board, "a"), _card(board, "b")
    assert k.kanban_link(a.id, b.id)["ok"] is True
    assert a.id in board.get(b.id).blocked_by


def test_link_refuses_self(board):
    a = _card(board, "a")
    assert k.kanban_link(a.id, a.id)["ok"] is False


def test_link_refuses_unknown_card(board):
    a = _card(board, "a")
    assert k.kanban_link(a.id, "card_missing")["ok"] is False


def test_link_refuses_a_cycle(board):
    """An orchestrator walking blocked_by would otherwise spin forever."""
    a, b, c = _card(board, "a"), _card(board, "b"), _card(board, "c")
    assert k.kanban_link(a.id, b.id)["ok"] is True   # b waits on a
    assert k.kanban_link(b.id, c.id)["ok"] is True   # c waits on b
    out = k.kanban_link(c.id, a.id)                  # a waits on c → cycle
    assert out["ok"] is False
    assert "cycle" in out["error"]


def test_create_with_parents_blocks_and_reports_rejects(board):
    a = _card(board, "a")
    out = k.kanban_create("child", parents=[a.id, "card_missing"])
    assert out["linked"] == [a.id]
    assert out["rejected_parents"] == ["card_missing"]
    assert board.get(out["id"]).column == "blocked"


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

def test_attach_file_from_workspace(board, tmp_path, monkeypatch):
    c = _card(board)
    target = tmp_path / "skills" / "artifact.txt"
    target.write_text("out", encoding="utf-8")
    monkeypatch.setattr(
        "jaeger_agent.workspace._resolve_read", lambda p: target)

    out = k.kanban_attach("artifact.txt", c.id)
    assert out["ok"] is True
    assert k.kanban_attachments(c.id)["attachments"][0]["filename"] == "artifact.txt"


def test_attach_rejects_a_path_outside_the_sandbox(board, monkeypatch):
    from jaeger_agent.workspace import SandboxError

    c = _card(board)

    def boom(_p):
        raise SandboxError("outside the workspace")

    monkeypatch.setattr("jaeger_agent.workspace._resolve_read", boom)
    out = k.kanban_attach("../../etc/passwd", c.id)
    assert out["ok"] is False
    assert "outside the workspace" in out["error"]
    assert board.get(c.id).attachments == []


def test_attach_url_validates_scheme(board):
    c = _card(board)
    assert k.kanban_attach_url("javascript:alert(1)", c.id)["ok"] is False
    assert k.kanban_attach_url("https://ok.test/pr/1", c.id)["ok"] is True


# ---------------------------------------------------------------------------
# task_id defaulting
# ---------------------------------------------------------------------------

def test_task_id_defaults_to_the_dispatched_card(board, monkeypatch):
    c = _card(board)
    monkeypatch.setenv("JAEGER_KANBAN_TASK", c.id)
    out = k.kanban_complete(summary="done without repeating the id")
    assert out["ok"] is True
    assert board.get(c.id).result == "done without repeating the id"


def test_missing_task_id_is_a_clear_error(board, monkeypatch):
    monkeypatch.delenv("JAEGER_KANBAN_TASK", raising=False)
    out = k.kanban_complete()
    assert out["ok"] is False
    assert "no task_id" in out["error"]


# ---------------------------------------------------------------------------
# Back-compat
# ---------------------------------------------------------------------------

def test_boards_written_before_this_change_still_load(board, tmp_path):
    """The new coordination fields must not break an existing board.json."""
    import json

    path = tmp_path / "memory" / "board.json"
    path.write_text(json.dumps({"cards": [
        {"title": "old card", "column": "ready", "id": "card_old",
         "description": "", "source": "user", "created_by": "user",
         "tags": [], "priority": "med", "created_at": 1.0, "updated_at": 1.0}
    ]}), encoding="utf-8")

    card = Board(path).get("card_old")
    assert card is not None
    assert card.title == "old card"
    assert card.comments == []
    assert card.blocked_by == []
    assert card.heartbeat_at is None
