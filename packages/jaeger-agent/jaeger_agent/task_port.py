"""The one door from agent code to the Gateway's durable task owner.

Agent code (tools, background reviewers) must not import the product package that
hosts it; the dependency runs the other way. So the two things it needs from the
host live here, in the agent package, and the host fills them in:

* the **task context** — set by the Gateway around a turn (:func:`task_scope`), it
  carries the task owner and the admitted session/execution, so a tool can queue
  background work without being handed authority by the model;
* the **remote client** — installed once by the host (:func:`install_remote`), used
  when there is no in-process owner (a terminal surface talking to the Gateway
  over HTTP).
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_context: ContextVar[Any] = ContextVar("gateway_task_context", default=None)
_remote: Any = None


@contextmanager
def task_scope(owner, *, session_id, request_id, execution, user_text, source="user"):
    token = _context.set(dict(owner=owner, session_id=session_id, request_id=request_id,
                              execution=execution or {}, user_text=user_text, source=source))
    try:
        yield
    finally:
        _context.reset(token)


def current_task_context():
    """The running turn's task context, or ``None`` outside a Gateway-owned turn."""
    return _context.get()


def install_remote(client: Any) -> None:
    """Register the host's HTTP task client (``tasks()``, ``submit(...)``)."""
    global _remote
    _remote = client


def remote() -> Any:
    """The installed remote task client, or ``None`` when the host has not provided one."""
    return _remote
