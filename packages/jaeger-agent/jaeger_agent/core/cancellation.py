"""Request-scoped cooperative cancellation across agent/runtime boundaries.

Hosts carry the event across IPC explicitly and bind it in the execution
thread. Cancelling is not a rollback: completed tool effects remain completed.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Event

_CURRENT: ContextVar[Event | None] = ContextVar("agent_turn_cancellation", default=None)


def current_cancellation() -> Event | None:
    return _CURRENT.get()


@contextmanager
def turn_cancellation(event: Event | None):
    token = _CURRENT.set(event)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def bind_turn_cancellation(method):
    """Bind the existing loop's interrupt event without replacing its loop."""
    @wraps(method)
    def run(agent, *args, **kwargs):
        event = current_cancellation()
        if event is None:
            return method(agent, *args, **kwargs)
        previous = agent._interrupt_event
        agent._interrupt_event = event
        try:
            return method(agent, *args, **kwargs)
        finally:
            # A late cancellation of this request must not cancel the next one.
            agent._interrupt_event = previous
    return run
