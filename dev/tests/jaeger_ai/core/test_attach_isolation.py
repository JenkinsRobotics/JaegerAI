"""A live agent may be running; the suite must never talk to it.

This is the regression pin for the Phase 0 isolation finding (F5). The bug was
not that two tests failed — it was WHY they failed: ``create_runtime`` tries
``run/bridge.sock`` before ``boot_for_tui``, so on any machine with a live
agent, a test that monkeypatched ``boot_for_tui`` never reached its own patch
and proxied real turns to the operator's real brain. CI has no live socket, so
CI could not see it; only the developer's machine went red.

The three tests below encode the three-part requirement literally:

  1. a live Jaeger runtime MAY exist  — ``_live_bridge`` stands a real one up,
  2. the test suite starts           — this module collects and runs,
  3. tests do not attach to it       — every attach path returns None.

``_live_bridge`` deliberately serves a REAL socket rather than mocking
``try_connect``. Mocking the connector would prove only that the mock was
called; binding a socket proves the policy holds against something that would
genuinely have accepted the connection.
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from jaeger_ai.core.runtime import attach_policy
from jaeger_ai.core.runtime import bridge_socket as bsock
from jaeger_ai.core.runtime.attached import try_attach_runtime
from jaeger_os.contract import protocol


class _LiveBridge:
    """A socket that really would hand out a runtime if anyone connected."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "run" / "bridge.sock"
        self.connections = 0
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> "_LiveBridge":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sock = bsock.bind(self.path)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except (OSError, TimeoutError):
                continue
            self.connections += 1
            try:
                text = conn.makefile("rw", buffering=1, encoding="utf-8", newline="\n")
                text.write(json.dumps(protocol.ready_frame("live", "real-model")) + "\n")
                text.flush()
            except OSError:
                pass

    def stop(self) -> None:
        self._stop.set()
        bsock.close_quietly(self._sock)
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.path.unlink(missing_ok=True)


@pytest.fixture
def live_bridge(bindable_instance_root):
    """A running bridge the suite is pointed straight at — and must ignore.

    ``bindable_instance_root`` pins ``JAEGER_INSTANCE_DIR`` AT the live socket,
    which is the most hostile arrangement available: resolution succeeds, the
    socket exists, and a connection would be accepted. Only the policy stands
    between the test and a live attach, which is exactly what needs proving.
    It does not lift ``JAEGER_NO_ATTACH`` — that is the point.
    """
    bridge = _LiveBridge(bindable_instance_root).start()
    yield bridge
    bridge.stop()


def test_the_suite_runs_with_a_live_bridge_and_does_not_attach(live_bridge):
    """(1) live runtime exists, (2) suite is running, (3) no attach."""
    assert live_bridge.path.exists(), "precondition: a real socket is listening"
    # Prove the socket really is live — this is the connection the policy must
    # prevent the runtime from making.
    probe = bsock.try_connect(live_bridge.path, timeout_s=2.0)
    assert probe is not None, "precondition: the bridge accepts connections"
    bsock.close_quietly(probe)
    accepted_by_probe = live_bridge.connections

    assert attach_policy.attach_disabled(), "conftest must disable attach suite-wide"
    assert try_attach_runtime(instance_name="live") is None
    assert live_bridge.connections == accepted_by_probe, (
        "try_attach_runtime opened a connection to the live bridge"
    )


def test_create_runtime_does_not_attach_to_a_live_bridge(live_bridge, monkeypatch):
    """The full factory path, not just the leaf function.

    ``AgentCore`` calls ``create_runtime``, which tries attachment first. With
    the policy on, it must fall through to the boot path — represented here by
    a sentinel so the test never loads a real model.
    """
    from jaeger_ai.core import mind_runtime

    class _Sentinel:
        attached = False

        def __init__(self, **_kw) -> None:
            pass

    monkeypatch.setattr(mind_runtime, "JaegerAIRuntime", _Sentinel)
    runtime = mind_runtime.create_runtime(bus=object(), config={"instance_name": "live"})

    assert isinstance(runtime, _Sentinel), "create_runtime attached instead of booting"
    assert live_bridge.connections == 0


def test_lifting_the_gate_is_what_makes_attach_possible(live_bridge, monkeypatch):
    """The gate is load-bearing, not incidental.

    Without this, a refactor that broke socket discovery entirely would leave
    the two tests above passing for the wrong reason — nothing attaches because
    nothing CAN. Lifting the policy must produce a real attachment against the
    same fixture, which is only safe because ``live_bridge`` is under tmp_path.
    """
    monkeypatch.delenv(attach_policy.ENV_NO_ATTACH, raising=False)
    assert not attach_policy.attach_disabled()

    runtime = try_attach_runtime(instance_name="live")
    assert runtime is not None, "attachment is broken; the tests above prove nothing"
    assert runtime.attached is True
    assert live_bridge.connections == 1
    runtime.close()


def test_policy_reads_the_documented_spellings(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on", " on "):
        monkeypatch.setenv(attach_policy.ENV_NO_ATTACH, value)
        assert attach_policy.attach_disabled(), value
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv(attach_policy.ENV_NO_ATTACH, value)
        assert not attach_policy.attach_disabled(), value
    monkeypatch.delenv(attach_policy.ENV_NO_ATTACH, raising=False)
    assert not attach_policy.attach_disabled()
