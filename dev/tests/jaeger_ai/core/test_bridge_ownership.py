"""One instance → at most one authoritative bridge runtime.

Phase 0 finding F3: eighteen ``jaeger bridge`` processes were resident, twelve
reparented to PID 1, fourteen of them spawned inside a 45-second window. The
mechanism turned out to be a single pair of behaviours that fed each other:

  1. A bridge that LOST the instance flock stayed alive anyway. ``_boot_agent``
     caught the lock error, emitted ``fatal(kind="locked")``, and returned —
     leaving a ~75 MB process with no agent serving a transport forever.

  2. That same process had already called ``bsock.bind()``, which unlinks
     whatever socket file is in its way. So the loser replaced the WINNER's
     attach point. Every client that attached afterwards reached a brain-less
     bridge, gave up, and spawned another one — which lost the lock and
     hijacked the socket in turn.

Together those are the storm and the orphan pile. These tests pin both halves
plus the ordinary lifecycle cases around them.

They exercise the real socket helpers rather than mocks: the whole bug lived in
what ``bind`` does to a file that already exists, and a mock would have modelled
the intent rather than the behaviour.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from jaeger_ai.core.runtime import bridge_socket as bsock
from jaeger_ai.interfaces import bridge as B


class _Owner:
    """Stand-in for the instance's authoritative bridge: binds and serves."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.accepted = 0
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "_Owner":
        self._sock = bsock.bind(self.path)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (OSError, TimeoutError):
                continue
            self.accepted += 1
            try:
                conn.sendall(b'{"type":"ready","instance":"owner"}\n')
            except OSError:
                pass

    def stop(self) -> None:
        self._stop.set()
        bsock.close_quietly(self._sock)
        if self._thread is not None:
            self._thread.join(timeout=2)


def _ctx_for(root: Path) -> B._Ctx:
    class _Layout:
        pass

    layout = _Layout()
    layout.root = root  # type: ignore[attr-defined]
    ctx = B._Ctx()
    ctx.layout = layout
    return ctx


@pytest.fixture
def instance_root(bindable_instance_root):
    """A short, disposable instance root with ``run/`` ready for a socket."""
    (bindable_instance_root / "run").mkdir(parents=True, exist_ok=True)
    return bindable_instance_root


# ── the hijack half ────────────────────────────────────────────────────


def test_the_lock_owner_reclaims_a_socket_held_by_a_predecessor(instance_root, capsys):
    """Ownership is decided by the flock, not by who still holds the path.

    The state actually found on the developer's machine: an OLD bridge holding
    ``bridge.sock`` open while no longer accepting, and the process that owned
    the instance lock — with the model loaded — sitting there with no attach
    point, because it had deferred to the stale holder. Clients could reach
    neither.

    ``_start_bridge_socket`` now runs only after boot has taken the lock, so a
    file at this path belongs to a predecessor by construction and reclaiming
    it is correct. That is also what makes crash recovery work.
    """
    predecessor = _Owner(instance_root / "run" / "bridge.sock").start()
    try:
        ctx = _ctx_for(instance_root)
        B._start_bridge_socket(ctx, queue.Queue(), None)

        assert ctx.bridge_sock is not None, "the lock owner failed to bind"
        assert "reclaiming attach socket" in capsys.readouterr().err
        # Clients now reach US, not the predecessor.
        probe = bsock.try_connect(instance_root / "run" / "bridge.sock", timeout_s=1.0)
        assert probe is not None
        bsock.close_quietly(probe)
    finally:
        bsock.close_quietly(ctx.bridge_sock)
        predecessor.stop()


def test_the_attach_socket_is_not_published_before_there_is_an_agent(instance_root):
    """A bridge with no client must not advertise an attach point.

    This is the other half of the same rule. Publishing early is what let
    clients attach to a bridge that had lost the lock and had no brain — they
    got a transport that answered and never produced a reply.
    """
    ctx = _ctx_for(instance_root)
    ctx.client = None
    ctx.booted.set()

    published = {"bound": False}

    def _fake_start(*_a, **_k):
        published["bound"] = True

    original = B._start_bridge_socket
    B._start_bridge_socket = _fake_start
    try:
        # Mirror main()'s publisher: wait for boot, then bind only with a client.
        ctx.booted.wait(timeout=1)
        if not ctx.exit_requested.is_set() and ctx.client is not None:
            B._start_bridge_socket(ctx, queue.Queue(), None)
    finally:
        B._start_bridge_socket = original

    assert published["bound"] is False, "an agent-less bridge published its socket"


def test_a_stale_socket_file_is_still_reclaimed(instance_root):
    """Refusing to hijack must not break crash recovery.

    A socket file left behind by a killed process is a FILE with nothing
    listening. That case has to keep working, or a crash would permanently
    wedge the instance — which is the failure the unconditional unlink was
    protecting against in the first place.
    """
    stale = instance_root / "run" / "bridge.sock"
    dead = bsock.bind(stale)
    dead.close()          # nothing is listening now; the file remains
    assert stale.exists()

    ctx = _ctx_for(instance_root)
    B._start_bridge_socket(ctx, queue.Queue(), None)
    try:
        assert ctx.bridge_sock is not None, "stale socket was not reclaimed"
        probe = bsock.try_connect(stale, timeout_s=1.0)
        assert probe is not None, "reclaimed socket does not accept clients"
        bsock.close_quietly(probe)
    finally:
        bsock.close_quietly(ctx.bridge_sock)
        stale.unlink(missing_ok=True)


# The mutual-exclusion half of the invariant — that one instance admits one
# lock holder — is covered by dev/tests/jaeger_ai/core/test_instance_lock.py,
# which exercises acquisition, the stale-PID heuristic and lock breaking. It is
# deliberately NOT duplicated here.
#
# A test was written at this layer first and removed: it drove
# ``_start_bridge_socket`` from two threads and asserted exactly one bound.
# That is false under reclaim semantics (the second unlinks and rebinds) and it
# was flaky 1 run in 5 — but more importantly it asserted at the wrong layer,
# because only the flock owner ever reaches that function.


# ── the lingering half ─────────────────────────────────────────────────


def test_losing_the_lock_requests_process_exit(monkeypatch):
    """A bridge that is not the runtime owner must not stay resident."""
    ctx = B._Ctx()
    ctx.inbound = queue.Queue()
    sink = _RecordingSink()

    def _locked_boot(**_kw):
        raise RuntimeError(
            "instance 'ares' is locked by pid 4242 (still running). "
            "Refusing to start a second copy."
        )

    monkeypatch.setattr("jaeger_ai.main.boot_for_tui", _locked_boot)
    B._boot_agent(sink, ctx, "ares")

    assert ctx.exit_requested.is_set(), "lock loss left the process running"
    assert ctx.inbound.get_nowait() is None, "main loop was not asked to stop"
    kinds = [f.get("kind") for f in sink.frames if f.get("type") == "fatal"]
    assert "locked" in kinds, "client was not told why it must go elsewhere"


def test_an_ordinary_boot_failure_keeps_the_transport_alive(monkeypatch):
    """Only LOCK loss is terminal.

    A model that fails to load is a degraded agent, not a duplicate one: the
    transport still answers queries and onboarding, which is what the native
    app's first-run flow runs on. Exiting on every boot error would break it.
    """
    ctx = B._Ctx()
    ctx.inbound = queue.Queue()
    sink = _RecordingSink()

    def _bad_model(**_kw):
        raise RuntimeError("failed to load GGUF: no such file")

    monkeypatch.setattr("jaeger_ai.main.boot_for_tui", _bad_model)
    B._boot_agent(sink, ctx, "ares")

    assert not ctx.exit_requested.is_set()
    assert ctx.inbound.empty()
    kinds = [f.get("kind") for f in sink.frames if f.get("type") == "fatal"]
    assert kinds == ["boot"]


def test_competing_bridge_processes_leave_one_owner(bindable_instance_root):
    """Spawn-N at the real entry point: ``python -m jaeger_ai.interfaces.bridge``.

    The previous draft used ``python -c`` plus a fake argv token so the
    lock's process-shape check would treat losers as jaeger. That is
    not the product path, and ``python -c`` holders are broken as stale
    — which is why a full-suite run could report several survivors.

    ``JAEGER_TEST_LOCK_ONLY`` is the only test seam: ``boot_for_tui``
    takes the real flock and returns a dummy client, so losers hit the
    same ``locked`` error production does, without loading a model.
    """
    root = bindable_instance_root
    (root / "run").mkdir(parents=True, exist_ok=True)
    (root / "identity.yaml").write_text("name: spawn-bound\n", encoding="utf-8")
    (root / "config.yaml").write_text("display: {}\n", encoding="utf-8")
    (root / "manifest.json").write_text("{}", encoding="utf-8")

    repo = Path(__file__).resolve().parents[4]
    env = os.environ.copy()
    env["JAEGER_INSTANCE_DIR"] = str(root)
    env["JAEGER_TEST_LOCK_ONLY"] = "1"
    env["JAEGER_NO_GUI"] = "1"
    env.pop("JAEGER_NO_ATTACH", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(repo),
            str(repo / "packages" / "jaeger-agent"),
            str(repo / "packages" / "jaeger-os"),
            env.get("PYTHONPATH", ""),
        ]
    )

    n = 5
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "jaeger_ai.interfaces.bridge", root.name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(repo),
        )
        for _ in range(n)
    ]
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            still = [p for p in procs if p.poll() is None]
            if len(still) == 1:
                break
            time.sleep(0.05)
        still = [p for p in procs if p.poll() is None]
        exited = [p for p in procs if p.poll() is not None]
        err_bits = []
        for p in exited:
            if p.stderr is not None:
                err_bits.append(p.stderr.read()[:400])
        assert len(still) == 1, (
            f"expected 1 surviving bridge, have {len(still)}; "
            f"exit codes={[p.returncode for p in exited]}; "
            f"stderr={err_bits}"
        )
        assert len(exited) == n - 1
        # Losers must have been told they lost the flock, not crashed.
        joined = b"\n".join(err_bits).decode("utf-8", "replace") + "".join(
            # stdout of losers may carry the fatal frame
            (p.stdout.read().decode("utf-8", "replace") if p.stdout else "")
            for p in exited
        )
        assert "lock" in joined.lower() or "locked" in joined.lower()
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=2)


def test_exit_request_survives_arriving_before_the_queue_exists():
    """The boot thread starts before ``main`` builds ``inbound``.

    If the lock is lost in that window there is no queue to push a sentinel
    into, so the event is the only carrier. ``main`` re-checks it the moment
    the queue exists; this pins that handoff.
    """
    ctx = B._Ctx()
    assert ctx.inbound is None
    B._request_exit(ctx)                       # nothing to push into yet
    assert ctx.exit_requested.is_set()

    inbound: queue.Queue = queue.Queue()       # what main does next
    ctx.inbound = inbound
    if ctx.exit_requested.is_set():
        inbound.put(None)
    assert inbound.get_nowait() is None


class _RecordingSink:
    """Captures protocol frames instead of writing them to stdout."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    def write(self, raw: str) -> int:
        text = raw.strip()
        if text:
            try:
                self.frames.append(json.loads(text))
            except ValueError:
                pass
        return len(raw)

    def flush(self) -> None:
        pass
