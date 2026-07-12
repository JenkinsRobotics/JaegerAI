"""Kanban board agent tools.

The agent's task-planning surface — see docs/kanban_design.md.

  • board_view(column, tag)        — read the board
  • board_add(title, …)            — add a card to the `ready` column
  • board_move(card_id, column)    — move a card between columns
  • board_update(card_id, …)       — edit a card / log progress on it
  • board_delete(card_id)          — remove a card

Five small, individual tools (not one action-dispatched umbrella) — a local
model routes over distinct named verbs better than over one tool's `action=`
parameter. The `kanban` SKILL carries the workflow (columns, when to file).

The board is one JSON file inside the instance (``memory/board.json``);
these tools are local bookkeeping and are NOT confirmation-gated — the
same low-risk class as ``remember``. The whole board is actionable
work — backlog included — so the agent can self-promote and pick up
cards autonomously when idle. The user still owns the board (anything
can be moved by hand via ``/board`` in the TUI). Deep Think jobs live
on this same board (``source="deepthink"``).
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.context import _require_layout
from jaeger_os.agent.background.board import COLUMNS, board_for_layout
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function


def _card_brief(card: Any) -> dict[str, Any]:
    """Compact card view for tool results."""
    out = {
        "id": card.id,
        "title": card.title,
        "column": card.column,
        "priority": card.priority,
        "source": card.source,
    }
    if card.tags:
        out["tags"] = card.tags
    if card.parent:
        out["parent"] = card.parent
    return out


@requires_tier(PermissionTier.READ_ONLY, skill="board", operation="board_view",
               summary="read the kanban board")
def board_view(column: str = "", tag: str = "") -> dict[str, Any]:
    """Read the kanban task board. Optionally filter by ``column``
    (backlog / ready / in_progress / blocked / done) or ``tag``.
    Use this to see what work is queued, in progress, or blocked."""
    board = board_for_layout(_require_layout())
    cards = board.list(column=column or None, tag=tag or None)
    return {
        "ok": True,
        "summary": board.summary(),
        "cards": [_card_brief(c) for c in cards],
    }


def board_add(
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    priority: str = "med",
    kind: str = "general",
) -> dict[str, Any]:
    """Add a card to the kanban board.

    ``kind`` picks the worker that will pick this card up when the
    user is idle:

      * ``"general"`` (default) — worked by the current loaded model
        on a normal turn. Right for routine tasks: small files,
        memory updates, notes, narrations, lookups.
      * ``"deepthink"`` — worked by the Deep Think coder model
        (model swap on entry). Right for hard tasks: skill authoring,
        long-form code, multi-step research that needs the strongest
        model in the toolbox.

    The card lands in ``ready`` (general) or ``backlog`` (deepthink —
    awaiting the user's approval before the model swap fires).
    ``priority`` is low / med / high."""
    clean = (title or "").strip()
    if not clean:
        return {"ok": False, "error": "empty card title"}
    kind_clean = (kind or "general").strip().lower()
    if kind_clean not in ("general", "deepthink"):
        return {"ok": False,
                "error": f"unknown kind {kind!r}; use 'general' or 'deepthink'"}
    board = board_for_layout(_require_layout())
    # Deep-think cards land in backlog (the user still approves the
    # model swap); general cards land in ready (work immediately).
    column = "backlog" if kind_clean == "deepthink" else "ready"
    source = "deepthink" if kind_clean == "deepthink" else "agent"
    card = board.add(
        clean, column=column, description=description,
        source=source, created_by="agent",
        tags=tags or [], priority=priority,
    )
    return {"ok": True, "card_id": card.id, "title": card.title,
            "column": card.column, "kind": kind_clean,
            "source": card.source}


def board_move(card_id: str, column: str) -> dict[str, Any]:
    """Move a card to another column — ``ready`` to promote it from
    backlog, ``in_progress`` when you start it, ``done`` when
    finished, ``blocked`` when it needs the user.

    The legacy approval gate (``backlog → ready`` was user-only) was
    removed when the agent gained autonomous backlog pickup: the
    whole board is now actionable work, and self-promotion is
    expected. The user still owns the board (they can move anything
    anywhere via ``/board``); the agent just doesn't have to wait."""
    board = board_for_layout(_require_layout())
    card = board.get(card_id)
    if card is None:
        return {"ok": False, "error": f"no card {card_id!r}"}
    if column not in COLUMNS:
        return {"ok": False, "error": f"unknown column {column!r}; "
                f"use one of {', '.join(COLUMNS)}"}
    moved = board.move(card_id, column)
    return {"ok": True, "card_id": card_id, "column": moved.column}


def board_update(
    card_id: str,
    title: str = "",
    description: str = "",
    priority: str = "",
    add_tag: str = "",
    note: str = "",
    result: str = "",
) -> dict[str, Any]:
    """Edit a card or log progress on it. ``note`` appends to the card's
    running log; ``result`` records the outcome; ``add_tag`` adds one
    tag. Empty arguments are left unchanged."""
    board = board_for_layout(_require_layout())
    card = board.get(card_id)
    if card is None:
        return {"ok": False, "error": f"no card {card_id!r}"}
    fields: dict[str, Any] = {}
    if title.strip():
        fields["title"] = title.strip()
    if description.strip():
        fields["description"] = description.strip()
    if priority.strip():
        fields["priority"] = priority.strip()
    if add_tag.strip() and add_tag.strip() not in card.tags:
        fields["tags"] = [*card.tags, add_tag.strip()]
    if note.strip():
        fields["notes"] = (card.notes + "\n" + note.strip()).strip()
    if result.strip():
        fields["result"] = result.strip()
    if not fields:
        return {"ok": False, "error": "nothing to update"}
    board.update(card_id, **fields)
    return {"ok": True, "card_id": card_id, "updated": sorted(fields)}


def board_delete(card_id: str) -> dict[str, Any]:
    """Remove a card from the board entirely (vs ``board_move`` to
    ``done``, which keeps it as a finished card)."""
    if not (card_id or "").strip():
        return {"ok": False, "error": "delete needs a card_id"}
    board = board_for_layout(_require_layout())
    if board.remove(card_id):
        return {"ok": True, "card_id": card_id, "deleted": True}
    return {"ok": False, "error": f"no card {card_id!r}"}


@register_tool_from_function(name="board_view", side_effect="read")
def _t_board_view(column: str = "", tag: str = "") -> dict:
    """Read the kanban task board — what work is queued (ready),
    in_progress, blocked, or done. Optionally filter by `column` or
    `tag`. Deep Think jobs show here too (tag 'deepthink')."""
    return board_view(column=column, tag=tag)


@register_tool_from_function(name="board_add")
def _t_board_add(
    title: str, description: str = "",
    tags: list[str] | None = None, priority: str = "med",
    kind: str = "general",
) -> dict:
    """Add a card to the kanban board (lands in `ready`, set to
    work). Use this to lay out a multi-step task as cards so you and
    the user can track progress. `priority` is low/med/high.
    `kind="deepthink"` files it for the Deep Think coder model (lands
    in `backlog` for the user to approve) — but for a genuine hard
    build/fix, prefer `propose_deep_think_task`."""
    return board_add(title=title, description=description,
                     tags=tags, priority=priority, kind=kind)


@register_tool_from_function(name="board_move")
def _t_board_move(card_id: str, column: str) -> dict:
    """Move a board card: `ready` to promote it from backlog,
    `in_progress` when you start it, `done` when finished, `blocked`
    when it needs the user. Self-promoting `backlog → ready` is
    allowed — the whole board is actionable work."""
    return board_move(card_id=card_id, column=column)


@register_tool_from_function(name="board_update")
def _t_board_update(
    card_id: str, title: str = "", description: str = "",
    priority: str = "", add_tag: str = "", note: str = "",
    result: str = "",
) -> dict:
    """Edit a board card or log progress on it. `note` appends to
    the card's running log; `result` records the outcome. Empty
    arguments are left unchanged."""
    return board_update(card_id=card_id, title=title,
                        description=description, priority=priority,
                        add_tag=add_tag, note=note, result=result)


@register_tool_from_function(name="board_delete")
def _t_board_delete(card_id: str) -> dict:
    """Delete a card from the kanban board by `card_id` — removes it
    entirely. To just finish a card, `board_move` it to `done` instead;
    use this only to discard one. For the board workflow (columns, when
    to file vs do), load the `kanban` skill (`use_skill(name="kanban")`)."""
    return board_delete(card_id=card_id)
