"""Kanban board agent tool.

The agent's task-planning surface — see docs/kanban_design.md. ONE
action-dispatched tool, ``kanban(action=…)``:
view / add / move / update / complete / block / unblock / delete.
(The ``board_view``/``board_add``/``board_move``/``board_update`` functions
below are the internal implementation that ``kanban`` and the TUI call; they
are no longer registered as separate agent tools — one board tool, not five.)

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
from jaeger_os.agent.schemas.tool_registry import register_tool_from_function


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


# ---------------------------------------------------------------------------
# Consolidated kanban tool — one tool, every board operation
# ---------------------------------------------------------------------------
def kanban(action: str, card_id: str = "", title: str = "",
           description: str = "", column: str = "", tag: str = "",
           priority: str = "", note: str = "",
           kind: str = "general") -> dict[str, Any]:
    """The kanban task board — ONE tool, action-dispatch. ``action``:

      - ``view``     — read the board (optional ``column`` / ``tag`` filter)
      - ``add``      — add a card: ``title`` (+ ``description`` / ``priority``
        low|med|high / ``tag`` / ``kind=general|deepthink``)
      - ``move``     — move card ``card_id`` to ``column``
      - ``update``   — edit / log on card ``card_id`` (``note`` appends a
        progress line)
      - ``complete`` — mark card ``card_id`` done
      - ``block``    — mark card ``card_id`` blocked (needs the user)
      - ``unblock``  — move a blocked card back to ready

    Columns: backlog / ready / in_progress / blocked / done.

    Card kinds: ``general`` (default — worked by the current model on
    a normal turn) vs ``deepthink`` (worked by the Deep Think coder
    model after the user approves it from backlog → ready). Pick
    deepthink for hard tasks that need the strongest model; pick
    general for routine work."""
    act = (action or "").strip().lower()
    if act in ("view", "show", "list", "read"):
        return board_view(column=column, tag=tag)
    if act in ("add", "create", "new"):
        return board_add(title=title, description=description,
                         tags=[tag.strip()] if tag.strip() else None,
                         priority=priority or "med",
                         kind=kind or "general")
    if act == "move":
        if not column:
            return {"ok": False, "error": "move needs a target column"}
        return board_move(card_id=card_id, column=column)
    if act in ("update", "comment", "log", "edit"):
        return board_update(card_id=card_id, title=title,
                            description=description, priority=priority,
                            add_tag=tag, note=note)
    if act in ("complete", "done", "finish"):
        return board_move(card_id=card_id, column="done")
    if act == "block":
        return board_move(card_id=card_id, column="blocked")
    if act in ("unblock", "resume"):
        return board_move(card_id=card_id, column="ready")
    if act in ("delete", "remove", "drop"):
        if not card_id:
            return {"ok": False, "error": "delete needs a card_id"}
        board = board_for_layout(_require_layout())
        if board.remove(card_id):
            return {"ok": True, "card_id": card_id, "deleted": True}
        return {"ok": False, "error": f"no card {card_id!r}"}
    return {"ok": False,
            "error": f"unknown kanban action {action!r} — use one of: view, "
                     "add, move, update, complete, block, unblock, delete"}


@register_tool_from_function(name="kanban")
def _t_kanban(action: str, card_id: str = "", title: str = "",
              description: str = "", column: str = "", tag: str = "",
              priority: str = "", note: str = "", kind: str = "general") -> dict:
    """The kanban task board — ONE tool for ALL board work. `action` selects the op:
      • view — read the board (optional `column`/`tag` filter)
      • add — add a card (`title`, optional `description`/`priority`
        low|med|high/`tag`/`kind` general|deepthink)
      • move — move card `card_id` to `column`
      • update / edit — edit or log on `card_id` (`note` appends a line)
      • complete — mark `card_id` done
      • block / unblock — mark `card_id` blocked, or send it back
      • delete — remove card `card_id` from the board
    Columns: backlog / ready / in_progress / blocked / done. Lay a
    multi-step task out as cards so you and the user can track it. To hand a
    hard build/fix to the strong model, use `propose_deep_think_task` (a board
    card alone does NOT queue Deep Think)."""
    return kanban(action=action, card_id=card_id, title=title,
                  description=description, column=column, tag=tag,
                  priority=priority, note=note, kind=kind)
