"""Closing must never hang, even when a socket was missed.

``zmq_ctx_term`` blocks until every socket in the context is closed —
no timeout, no interrupt. A missed socket wedges the process at exit
inside poll(): unkillable by Ctrl-C, invisible in a Python traceback,
and indistinguishable from a busy app. Two processes sat in this
machine's table for two days that way; `sample` showed both parked in
``zmq::ctx_t::terminate()``. These pin the bound that makes that
impossible.
"""

from __future__ import annotations

import threading
import time

import pytest

zmq = pytest.importorskip("zmq")

from jaeger_os.transport.zmq_bus import term_context


def test_an_unclosed_socket_does_not_hang_forever():
    """THE regression. A raw ctx.term() here never returns."""
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.bind("inproc://leaked")     # deliberately never closed

    t0 = time.perf_counter()
    term_context(ctx, "test", timeout_s=1.0)
    elapsed = time.perf_counter() - t0

    # destroy(linger=0) closes it for us, so this usually SUCCEEDS
    # quickly — the point is only that it is bounded either way.
    assert elapsed < 5.0, f"took {elapsed:.1f}s — the bound did not hold"


def test_it_reports_a_timeout_rather_than_blocking(monkeypatch, capfd):
    """When destroy itself wedges, the deadline still releases us."""
    class Wedged:
        def destroy(self, linger=0):
            threading.Event().wait()      # never returns, like a real one

    t0 = time.perf_counter()
    assert term_context(Wedged(), "wedged", timeout_s=0.5) is False
    assert time.perf_counter() - t0 < 3.0
    assert "did not terminate" in capfd.readouterr().err


def test_the_clean_case_still_terminates():
    ctx = zmq.Context()
    ctx.socket(zmq.PUB).close(linger=0)
    assert term_context(ctx, "clean", timeout_s=5.0) is True


def test_the_worker_is_a_daemon():
    """The whole guarantee rests on this: an abandoned term thread must
    not hold the interpreter open, or 'bounded' just moves the hang."""
    before = set(threading.enumerate())

    class Wedged:
        def destroy(self, linger=0):
            threading.Event().wait()

    term_context(Wedged(), "daemoncheck", timeout_s=0.3)
    new = [t for t in threading.enumerate() if t not in before]
    assert new, "no worker thread was started"
    assert all(t.daemon for t in new), "an abandoned term thread is not daemon"
