"""The one door from agent code to the Gateway's durable task owner.

Agent code (tools, background reviewers) must not import the product package that
hosts it; the dependency runs the other way. So the two things it needs from the
host live here, in the agent package, and the host fills them in:

* the **task context** — set by the Gateway around a turn (:func:`task_scope`), it
  carries the task owner and the admitted session/execution, so a tool can queue
  background work without being handed authority by the model;
* the **remote client** — installed once by the host (:func:`install_remote`), used
  when there is no in-process owner (a terminal surface talking to the Gateway
  over HTTP);
* the **IDE requester** — installed by the Gateway (:func:`install_ide_requester`),
  used by the ``ide_*`` tools to ask the operator's editor to do something (open a
  file, list problems) and wait for its answer.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_context: ContextVar[Any] = ContextVar("gateway_task_context", default=None)
_remote: Any = None
_ide_requester: Any = None


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


def install_ide_requester(requester: Any) -> None:
    """Register ``requester(session_id, request_id, kind, args, timeout) -> dict``."""
    global _ide_requester
    _ide_requester = requester


def ide_request(kind: str, args: dict[str, Any] | None = None, *, timeout: float = 10.0) -> dict[str, Any]:
    """Ask the operator's IDE to do ``kind`` and return its answer.

    Fails cleanly, never hangs: outside a Gateway turn, or when no IDE answers
    within ``timeout``, the result is ``{"ok": False, "error": ...}``.
    """
    context = current_task_context()
    if context is None or _ide_requester is None:
        return {"ok": False, "error": "No IDE is connected to this conversation"}
    return _ide_requester(context["session_id"], context["request_id"], kind, dict(args or {}), timeout)
