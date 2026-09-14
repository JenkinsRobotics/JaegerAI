"""The manifest's ``[bus] backend`` is honoured — both modes work.

In-process is the default and is why frames cost nothing (the bus passes
references). But some nodes want isolation: a crash-prone driver, a
GPL-licensed decoder, anything that must not take the app down with it.

Before this, `_build_bus()` unconditionally built an `InProcBus` and
never read `spec.bus.backend`. The manifest declared the backend,
VALIDATED it (refusing subprocess-on-inproc), logged it — and ignored
it. Which made `backend = "subprocess"` unreachable: it requires a ZMQ
bus, and no manifest could produce one.
"""

from __future__ import annotations

import pathlib
import time

import pytest

from jaeger_os.app.app import JaegerApp
from jaeger_os.app.manifest import load_manifest
from jaeger_os.transport import InProcBus, topics
from jaeger_os.transport.broker import Broker
from jaeger_os.transport.zmq_bus import ZMQBus

pytestmark = pytest.mark.integration

_INPROC = '''\
[app]
name = "t"
requires_framework = ">=0.1"
mode = "fused"
event_loop = "none"
config = ""

[bus]
backend = "inproc"
'''

_ZMQ = '''\
[app]
name = "t"
requires_framework = ">=0.1"
mode = "fused"
event_loop = "none"
config = ""

[bus]
backend = "zmq"
xsub = "ipc:///tmp/jros-test-xsub.sock"
xpub = "ipc:///tmp/jros-test-xpub.sock"
'''

_ZMQ_WITH_WORKER = _ZMQ + '''
[[node]]
id = "worker"
tier = 3
backend = "subprocess"
module = "dev.tests.jaeger_os.app._zmq_worker_node"
restart = "never"
enabled = true
'''


def _app(tmp_path: pathlib.Path, manifest: str) -> JaegerApp:
    (tmp_path / "jaeger.toml").write_text(manifest)
    return JaegerApp(tmp_path / "jaeger.toml")


# ── the default stays the default ────────────────────────────────

def test_inproc_is_the_default(tmp_path):
    app = _app(tmp_path, _INPROC)
    try:
        app.boot()
        assert isinstance(app.bus, InProcBus)
        assert app._broker is None, "no broker for an in-process bus"
    finally:
        app.shutdown()


# ── zmq is honoured ──────────────────────────────────────────────

def test_zmq_backend_builds_a_zmq_bus_and_a_broker(tmp_path):
    app = _app(tmp_path, _ZMQ)
    try:
        app.boot()
        assert isinstance(app.bus, ZMQBus), (
            f"backend=zmq produced {type(app.bus).__name__}")
        assert isinstance(app._broker, Broker)
    finally:
        app.shutdown()


def test_the_broker_publishes_its_endpoints_for_children(tmp_path):
    """A subprocess node finds the bus ONLY through the environment its
    parent hands it. That env is the entire parent/child contract."""
    app = _app(tmp_path, _ZMQ)
    try:
        app.boot()
        env = app._broker.env()
        assert env["JAEGER_TRANSPORT_XSUB"] == "ipc:///tmp/jros-test-xsub.sock"
        assert env["JAEGER_TRANSPORT_XPUB"] == "ipc:///tmp/jros-test-xpub.sock"
    finally:
        app.shutdown()


def test_a_zmq_bus_round_trips_in_process(tmp_path):
    app = _app(tmp_path, _ZMQ)
    seen = []
    try:
        app.boot()
        app.bus.subscribe(topics.SYS_NODE_HEALTH, seen.append)
        time.sleep(0.3)  # SUB filters need to reach the broker
        app.bus.publish(topics.NodeHealth(node="x", state="RUNNING"))
        deadline = time.monotonic() + 3.0
        while not seen and time.monotonic() < deadline:
            time.sleep(0.02)
        assert seen, "nothing came back over the zmq bus"
    finally:
        app.shutdown()


# ── the point: a node in its OWN process ─────────────────────────

def test_a_subprocess_node_reaches_the_parent_bus(tmp_path, monkeypatch):
    """Two processes, one bus. This is what isolation has to mean, and
    it was unreachable before the backend was wired."""
    # SubprocessHandle prepends the app root to the child's PYTHONPATH.
    # A real node module is an installed package; this worker lives in
    # the repo, so point at it explicitly.
    repo = pathlib.Path(__file__).resolve().parents[4]
    monkeypatch.setenv("PYTHONPATH", str(repo))
    app = _app(tmp_path, _ZMQ_WITH_WORKER)
    seen = []
    try:
        app.boot()
        app.bus.subscribe(topics.SYS_NODE_HEALTH, seen.append)
        deadline = time.monotonic() + 15.0
        while not seen and time.monotonic() < deadline:
            time.sleep(0.05)
        assert seen, "no heartbeat from the subprocess node"
        assert any("separate process" in (m.detail or "") for m in seen)
    finally:
        app.shutdown()


def test_shutdown_stops_the_broker(tmp_path):
    app = _app(tmp_path, _ZMQ)
    app.boot()
    broker = app._broker
    app.shutdown()
    assert not broker._started, "broker left running after shutdown"


# ── the guard that made this reachable in the first place ────────

def test_subprocess_on_inproc_is_still_refused(tmp_path):
    """A separate process cannot share an in-process queue. The manifest
    refusing this is what makes the zmq path required rather than
    optional."""
    bad = _INPROC + (
        '\n[[node]]\nid = "w"\nbackend = "subprocess"\n'
        'module = "dev.tests.jaeger_os.app._zmq_worker_node"\n'
    )
    (tmp_path / "jaeger.toml").write_text(bad)
    with pytest.raises(ValueError, match="zmq"):
        load_manifest(tmp_path / "jaeger.toml")
