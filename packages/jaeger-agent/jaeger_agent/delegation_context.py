"""Who is running this turn — the main session, or a delegated child?

Ported from hermes-agent ``agent/delegation_context.py`` (MIT — Copyright
(c) 2025 Nous Research), which exists to answer one question for the kanban
tools: is the caller a dispatcher-owned worker that legitimately owns a board
card, or a ``delegate_task`` child that merely inherited the environment?

The donor's reasoning, which applies verbatim to Jaeger:

    A delegate_task child runs in the same process as its parent, so stale
    or inherited HERMES_KANBAN_* env vars are not proof of dispatcher
    ownership. The child may summarize findings to its parent, but it must
    not complete, block, heartbeat, comment, create, link, or unblock board
    tasks directly.

Jaeger's children are *always* in-process (``main.py::_delegate_internal``
builds a fresh ``JaegerAgent`` on the same interpreter), so the ambiguity the
donor guards against is not an edge case here — it is the only case. A
ContextVar is the right carrier: it is inherited by tasks and threads the
child spawns, so a grandchild is correctly identified as delegated too.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_delegated: ContextVar[bool] = ContextVar("jaeger_delegated_child", default=False)


def is_delegated_child_context() -> bool:
    """True when the current turn belongs to a ``delegate_task`` child."""
    return _delegated.get()


@contextmanager
def delegated_child() -> Iterator[None]:
    """Mark the enclosed turn as a delegated child's."""
    token = _delegated.set(True)
    try:
        yield
    finally:
        _delegated.reset(token)


def kanban_task_id() -> str:
    """The board card this process was dispatched to own, or "".

    Set by the dispatcher when it spawns a worker for a specific card. A
    delegated child may observe this variable through plain environment
    inheritance, which is exactly why :func:`is_dispatcher_owned_worker`
    exists rather than callers testing the env var directly.
    """
    return os.environ.get("JAEGER_KANBAN_TASK", "").strip()


def is_dispatcher_owned_worker() -> bool:
    """True only when this turn genuinely owns a dispatched board card.

    False for delegate_task children even when ``JAEGER_KANBAN_TASK`` is
    visible to them, and false when no card was dispatched at all.
    """
    if is_delegated_child_context():
        return False
    return bool(kanban_task_id())


__all__ = [
    "delegated_child",
    "is_delegated_child_context",
    "is_dispatcher_owned_worker",
    "kanban_task_id",
]
