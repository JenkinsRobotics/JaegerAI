"""Kanban tools — the structured surface for worker + orchestrator agents.

Ported from hermes-agent ``tools/kanban_tools.py``. hermes-agent is MIT
licensed:

    Copyright (c) 2025 Nous Research

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software.

WHY THIS EXISTS IN JAEGER. Jaeger already shipped three skills —
``devops/kanban-orchestrator``, ``devops/kanban-worker`` and
``productivity/kanban`` — whose text instructs the model to heartbeat,
request review, block on dependencies and attach artifacts. The board tool
surface was five verbs (``board_add``/``view``/``move``/``update``/
``delete``), so those instructions named calls that did not exist. This
module closes that gap: the skills now describe a protocol the tools can
actually execute.

The donor's rationale for tools over shelling out to a CLI is preserved,
minus the one reason that does not apply here:

  1. **Backend portability** — a worker whose terminal points at Docker or
     SSH cannot reach the board through a CLI that is not installed in the
     container. Tools run in the agent's own process. (Applies to Jaeger.)
  2. **No shell-quoting footguns** — structured tool args skip shlex and
     argparse entirely. (Applies.)
  3. **Better errors** — a failed tool call returns structured data the
     model can reason about, not a stderr string it has to parse. (Applies.)

GATING, and why it matters. These tools are registered but hidden unless the
turn is a dispatcher-owned worker (``JAEGER_KANBAN_TASK`` set) or the
``kanban`` toolset is explicitly loaded. A plain chat turn sees zero kanban
tools, matching the donor. Mutations are additionally refused for
``delegate_task`` children — see :mod:`jaeger_agent.delegation_context` for
why an inherited env var is not proof of ownership.

ADAPTATIONS:

  - The donor's SQLite board becomes Jaeger's existing per-instance JSON
    board (:mod:`jaeger_agent.background.board`), so there is one task
    surface rather than two competing ones.
  - ``kanban_attach`` takes a workspace path rather than base64 bytes: the
    JSON board is rewritten whole on every mutation, so inlining artifact
    bytes would rewrite them on every unrelated card update. The path is
    sandbox-resolved, so a card cannot be used to smuggle a reference to a
    file outside the workspace.
  - ``task_id`` defaults to the dispatched card, so a worker calls
    ``kanban_complete(summary=...)`` without repeating an id it was given.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function

from jaeger_agent.delegation_context import (
    is_delegated_child_context,
    kanban_task_id,
)


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

def _kanban_mode() -> bool:
    """Whether the kanban surface is available to this turn.

    Available when the process was dispatched to own a card, or when the
    ``kanban`` toolset has been explicitly loaded (the orchestrator case).
    Matches the donor: an ordinary chat session sees none of these tools.
    """
    if kanban_task_id():
        return True
    try:
        from jaeger_agent.skill_registry.toolset_scoping import (
            active_toolset_names,
        )
        return "kanban" in active_toolset_names()
    except Exception:  # noqa: BLE001 — gating must never raise
        return False


def _board():
    from jaeger_agent.background.board import board_for_layout
    from jaeger_agent.workspace import get_layout

    return board_for_layout(get_layout())


def _resolve(task_id: str) -> str:
    """Explicit id wins; otherwise the card this worker was dispatched to."""
    return (task_id or "").strip() or kanban_task_id()


def _guard_mutation(tool: str) -> dict[str, Any] | None:
    """Refuse board mutations from delegate_task children.

    Returns an error dict to hand straight back to the model, or None when
    the call may proceed. The message tells the child what to do instead —
    a bare refusal would leave it retrying.
    """
    if is_delegated_child_context():
        return {
            "ok": False,
            "error": (
                f"{tool} refused: delegate_task child agents are not board "
                "run owners. Return your findings to the parent agent; the "
                "dispatcher worker or a configured kanban orchestrator "
                "performs board mutations."
            ),
        }
    return None


def _need_id(task_id: str, tool: str) -> dict[str, Any] | None:
    if not task_id:
        return {
            "ok": False,
            "error": (
                f"{tool}: no task_id given and this turn was not dispatched "
                "to a card. Pass task_id explicitly."
            ),
        }
    return None


def _brief(card: Any) -> dict[str, Any]:
    """The card projection the model sees. Deliberately not the whole card:
    comments and attachments can be long, and ``kanban_show`` is the verb
    that returns them in full."""
    return {
        "id": card.id,
        "title": card.title,
        "column": card.column,
        "assignee": card.assignee,
        "priority": card.priority,
        "tags": list(card.tags),
        "blocked_by": list(card.blocked_by),
        "review_state": card.review_state,
        "comments": len(card.comments),
        "attachments": len(card.attachments),
    }


# ---------------------------------------------------------------------------
# Read verbs
# ---------------------------------------------------------------------------

@register_tool_from_function(
    name="kanban_show", toolset="kanban", side_effect="read",
    check_fn=_kanban_mode,
)
def kanban_show(task_id: str = "") -> dict:
    """Show one board card in full — description, comments, attachments,
    block reason and review state. Defaults to the card this worker was
    dispatched to own, so a worker can call it with no arguments."""
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_show")):
        return err
    card = _board().get(tid)
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    out = _brief(card)
    out.update({
        "ok": True,
        "description": card.description,
        "notes": card.notes,
        "result": card.result,
        "block_reason": card.block_reason,
        "block_kind": card.block_kind,
        "review_summary": card.review_summary,
        "review_feedback": card.review_feedback,
        "reviewer": card.reviewer,
        "heartbeat_at": card.heartbeat_at,
        "comments": list(card.comments),
        "attachments": list(card.attachments),
    })
    return out


@register_tool_from_function(
    name="kanban_list", toolset="kanban", side_effect="read",
    check_fn=_kanban_mode,
)
def kanban_list(
    assignee: str = "", status: str = "", tag: str = "", limit: int = 50,
) -> dict:
    """List board cards, newest pipeline order first. Filter by ``assignee``,
    ``status`` (a column: backlog / ready / in_progress / blocked / done) or
    ``tag``. Use this to find work, then kanban_show for one card's detail."""
    cards = _board().list(column=status or None, tag=tag or None)
    if assignee:
        cards = [c for c in cards if c.assignee == assignee]
    try:
        capped = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        capped = 50
    return {
        "ok": True,
        "count": len(cards),
        "shown": min(len(cards), capped),
        "cards": [_brief(c) for c in cards[:capped]],
    }


@register_tool_from_function(
    name="kanban_attachments", toolset="kanban", side_effect="read",
    check_fn=_kanban_mode,
)
def kanban_attachments(task_id: str = "") -> dict:
    """List the artifacts attached to a card — files produced by a worker
    and URLs it recorded."""
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_attachments")):
        return err
    card = _board().get(tid)
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "task_id": tid, "attachments": list(card.attachments)}


# ---------------------------------------------------------------------------
# Lifecycle verbs
# ---------------------------------------------------------------------------

@register_tool_from_function(
    name="kanban_create", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_create(
    title: str,
    body: str = "",
    assignee: str = "",
    tags: list[str] | None = None,
    priority: str = "med",
    parents: list[str] | None = None,
) -> dict:
    """Create a board card. ``parents`` lists cards this one depends on —
    it starts blocked until they are done. Use for work that outlives the
    current turn; use ``todo`` for within-turn steps."""
    if (err := _guard_mutation("kanban_create")):
        return err
    clean = (title or "").strip()
    if not clean:
        return {"ok": False, "error": "kanban_create: title is required"}
    board = _board()
    card = board.add(
        clean, description=(body or "").strip(), tags=list(tags or []),
        priority=priority, source="agent", created_by="agent",
    )
    if assignee:
        board.update(card.id, assignee=assignee)
    linked, rejected = [], []
    for parent in (parents or []):
        (linked if board.link(parent, card.id) else rejected).append(parent)
    if linked:
        board.block(card.id, f"waiting on {', '.join(linked)}", "dependency")
    out = {"ok": True, "id": card.id, "title": card.title,
           "column": board.get(card.id).column, "linked": linked}
    if rejected:
        # Surfaced, not swallowed: a dependency the caller believes exists
        # but that was refused (unknown id, or it would close a cycle) means
        # this card is NOT waiting on what the caller thinks it is.
        out["rejected_parents"] = rejected
    return out


@register_tool_from_function(
    name="kanban_complete", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_complete(task_id: str = "", summary: str = "") -> dict:
    """Mark your card done and record what you produced. ``summary`` is what
    the orchestrator reads, so state the outcome, not the effort."""
    if (err := _guard_mutation("kanban_complete")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_complete")):
        return err
    card = _board().complete(tid, summary)
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "column": card.column,
            "result": card.result}


@register_tool_from_function(
    name="kanban_block", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_block(task_id: str = "", reason: str = "", kind: str = "") -> dict:
    """Park your card because you cannot proceed. ``reason`` must say what
    would unblock it. ``kind`` is a hint for the orchestrator — e.g.
    "dependency" (waiting on other work) or "input" (needs a human)."""
    if (err := _guard_mutation("kanban_block")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_block")):
        return err
    clean = (reason or "").strip()
    if not clean:
        return {"ok": False, "error": (
            "kanban_block: a reason is required — a parked card with no "
            "reason cannot be unblocked by anyone else.")}
    card = _board().block(tid, clean, (kind or "").strip())
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "column": card.column,
            "block_reason": card.block_reason}


@register_tool_from_function(
    name="kanban_unblock", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_unblock(task_id: str = "", column: str = "ready") -> dict:
    """Return a parked card to the flow once its blocker is resolved."""
    if (err := _guard_mutation("kanban_unblock")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_unblock")):
        return err
    card = _board().unblock(tid, column)
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "column": card.column}


@register_tool_from_function(
    name="kanban_heartbeat", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_heartbeat(task_id: str = "", note: str = "") -> dict:
    """Signal that you are still working. Call this during long work so the
    orchestrator can tell a live worker from one that died holding a card —
    an in_progress card with a stale heartbeat is the signal to reassign."""
    if (err := _guard_mutation("kanban_heartbeat")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_heartbeat")):
        return err
    card = _board().heartbeat(tid, (note or "").strip())
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "heartbeat_at": card.heartbeat_at}


@register_tool_from_function(
    name="kanban_comment", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_comment(body: str, task_id: str = "") -> dict:
    """Append a comment to a card. Comments are the handoff channel between
    agents working the same board, and are append-only."""
    if (err := _guard_mutation("kanban_comment")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_comment")):
        return err
    clean = (body or "").strip()
    if not clean:
        return {"ok": False, "error": "kanban_comment: body is required"}
    card = _board().comment(tid, clean)
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "comments": len(card.comments)}


@register_tool_from_function(
    name="kanban_request_review", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_request_review(
    task_id: str = "", summary: str = "", reviewer: str = "",
) -> dict:
    """Hand your card back for review instead of closing it. Use this when
    the work is done but someone should check it before it counts."""
    if (err := _guard_mutation("kanban_request_review")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_request_review")):
        return err
    card = _board().request_review(tid, (summary or "").strip(),
                                   (reviewer or "").strip())
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "review_state": card.review_state}


@register_tool_from_function(
    name="kanban_request_changes", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_request_changes(reason: str, task_id: str = "") -> dict:
    """Bounce a reviewed card back to its worker with feedback. Moves the
    card back to in_progress — a card awaiting rework is not done."""
    if (err := _guard_mutation("kanban_request_changes")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_request_changes")):
        return err
    clean = (reason or "").strip()
    if not clean:
        return {"ok": False, "error": (
            "kanban_request_changes: a reason is required — the worker "
            "cannot act on a bounce with no feedback.")}
    card = _board().request_changes(tid, clean)
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "column": card.column,
            "review_state": card.review_state}


@register_tool_from_function(
    name="kanban_link", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_link(parent_id: str, child_id: str) -> dict:
    """Record that ``child_id`` depends on ``parent_id``. Refused if either
    card is unknown, if they are the same card, or if the link would close a
    dependency cycle."""
    if (err := _guard_mutation("kanban_link")):
        return err
    if not _board().link((parent_id or "").strip(), (child_id or "").strip()):
        return {"ok": False, "error": (
            "link refused: unknown card, self-link, or it would create a "
            "dependency cycle")}
    return {"ok": True, "parent_id": parent_id, "child_id": child_id}


@register_tool_from_function(
    name="kanban_attach", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_attach(path: str, task_id: str = "", content_type: str = "") -> dict:
    """Attach a workspace file to a card so the orchestrator can find what
    you produced. ``path`` is resolved inside the workspace sandbox."""
    if (err := _guard_mutation("kanban_attach")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_attach")):
        return err
    from jaeger_agent.workspace import SandboxError, _resolve_read
    try:
        resolved = _resolve_read(path)
    except SandboxError as e:
        return {"ok": False, "error": f"kanban_attach: {e}"}
    if not resolved.is_file():
        return {"ok": False, "error": f"kanban_attach: no such file: {path}"}
    card = _board().attach(
        tid, kind="file", ref=str(resolved), filename=resolved.name,
        content_type=content_type,
    )
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "attached": str(resolved),
            "attachments": len(card.attachments)}


@register_tool_from_function(
    name="kanban_attach_url", toolset="kanban", check_fn=_kanban_mode,
)
def kanban_attach_url(
    url: str, task_id: str = "", filename: str = "", content_type: str = "",
) -> dict:
    """Attach a URL to a card — a PR, a build, a published artifact."""
    if (err := _guard_mutation("kanban_attach_url")):
        return err
    tid = _resolve(task_id)
    if (err := _need_id(tid, "kanban_attach_url")):
        return err
    clean = (url or "").strip()
    if not clean.startswith(("http://", "https://")):
        return {"ok": False, "error": (
            "kanban_attach_url: url must start with http:// or https://")}
    card = _board().attach(
        tid, kind="url", ref=clean, filename=filename,
        content_type=content_type,
    )
    if card is None:
        return {"ok": False, "error": f"no card with id {tid!r}"}
    return {"ok": True, "id": card.id, "attached": clean,
            "attachments": len(card.attachments)}


__all__ = [
    "kanban_attach", "kanban_attach_url", "kanban_attachments",
    "kanban_block", "kanban_comment", "kanban_complete", "kanban_create",
    "kanban_heartbeat", "kanban_link", "kanban_list",
    "kanban_request_changes", "kanban_request_review", "kanban_show",
    "kanban_unblock",
]
