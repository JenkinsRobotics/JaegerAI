"""Live event seam: lets code deep inside a turn (a delegate, a long tool, a
hook) report to the host's event stream without importing the host.

The host (the Gateway) binds an emitter for the turn with :func:`bind`; the
agent loop marks the tool call being dispatched with :func:`tool_call`. Both
are ContextVars, so they follow ``copy_context()`` into worker threads and are
absent (a no-op) in a bare CLI or test run.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

Emitter = Callable[[str, dict[str, Any]], None]

_emitter: ContextVar[Emitter | None] = ContextVar("jaeger_live_emitter", default=None)
_tool_call: ContextVar[str | None] = ContextVar("jaeger_live_tool_call", default=None)
_subagent: ContextVar[str | None] = ContextVar("jaeger_live_subagent", default=None)


@contextmanager
def bind(emitter: Emitter | None) -> Iterator[None]:
    token = _emitter.set(emitter)
    try:
        yield
    finally:
        _emitter.reset(token)


@contextmanager
def tool_call(call_id: str | None) -> Iterator[None]:
    token = _tool_call.set(str(call_id) if call_id else None)
    try:
        yield
    finally:
        _tool_call.reset(token)


def current_tool_call() -> str | None:
    return _tool_call.get()


@contextmanager
def subagent(subagent_id: str | None) -> Iterator[None]:
    """Mark work below as running inside sub-agent ``subagent_id``."""
    token = _subagent.set(subagent_id)
    try:
        yield
    finally:
        _subagent.reset(token)


def current_subagent() -> str | None:
    return _subagent.get()


def active() -> bool:
    return _emitter.get() is not None


def emit(event: str, data: dict[str, Any] | None = None) -> None:
    """Publish ``event`` on the bound host stream; stamps the current tool call and sub-agent."""
    fn = _emitter.get()
    if fn is None:
        return
    payload = dict(data or {})
    call = _tool_call.get()
    if call and "call_id" not in payload:
        payload["call_id"] = call
    sub = _subagent.get()
    if sub and "subagent_id" not in payload:
        payload["subagent_id"] = sub
    try:
        fn(event, payload)
    except Exception:  # noqa: BLE001 — reporting never breaks the work
        logger.debug("live emit %s failed", event, exc_info=True)


def progress(message: str = "", *, fraction: float | None = None, **extra: Any) -> None:
    """Report progress on the current tool call (MCP-style progress/total)."""
    data: dict[str, Any] = {"message": str(message)[:300], **extra}
    if fraction is not None:
        data["fraction"] = max(0.0, min(1.0, float(fraction)))
    emit("tool.progress", data)


__all__ = ["bind", "tool_call", "current_tool_call", "subagent", "current_subagent", "active", "emit", "progress"]
