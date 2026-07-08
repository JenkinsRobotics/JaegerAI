"""Conformance tests for the Jaeger app format (format 0.1).

THIS FILE IS PART OF WHAT YOU COPY: it runs against whichever chassis
copy sits next to it, in that app's own venv. Boot order, node
lifecycle, supervisor verbs + restart policy, manifest/config
refusals, single-instance, no-orphans teardown — the spec'd contract,
executable.
"""

from __future__ import annotations

import dataclasses
import pathlib
import subprocess
import sys
import time
from typing import Any

import pytest


from jaeger_os.app import FRAMEWORK_FORMAT, JaegerApp  # noqa: E402
from jaeger_os.app.app import SecondInstanceError, resolve_ref  # noqa: E402
from jaeger_os.app.core import Core, CoreMainThreadError  # noqa: E402
from jaeger_os.transport import InProcBus  # noqa: E402
from jaeger_os.app.config import load_config, slice_for  # noqa: E402
from jaeger_os.app.health import HealthCache  # noqa: E402
from jaeger_os.transport import topics  # noqa: E402
from jaeger_os.app.manifest import load_manifest  # noqa: E402
from jaeger_os.nodes.base import FrameNode, Node, NodeState  # noqa: E402
from jaeger_os.app import supervisor as supervisor_mod  # noqa: E402
from jaeger_os.app.supervisor import (  # noqa: E402
    Supervisor,
    ThreadHandle,
    reap_stale,
)
from jaeger_os.app.manifest import NodeSpec  # noqa: E402
import jaeger_os.app as app_pkg  # noqa: E402
import jaeger_os.nodes.base as nodes_base_mod  # noqa: E402


def _wait_for(cond, timeout_s=3.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ── messages used by the in-file test nodes ────────────────────────


@dataclasses.dataclass
class Ping:
    n: int = 0
    topic: str = "/test/ping"


class TickerNode(Node):
    def __init__(self, *, bus: Any, **_: Any) -> None:
        super().__init__(bus=bus, name="ticker", tick_interval_s=0.01)
        self.ticks = 0

    def tick(self) -> None:
        self.ticks += 1
        time.sleep(0.01)


def make_ticker(bus: Any, config: dict[str, Any]) -> Node:
    return TickerNode(bus=bus, **config)


class DyingNode(Node):
    """Runs ~50 ms then stops itself — the restart-policy fixture."""

    def __init__(self, *, bus: Any, **_: Any) -> None:
        super().__init__(bus=bus, name="dying", tick_interval_s=0.01)

    def tick(self) -> None:
        time.sleep(0.05)
        self.stop()


def make_dying(bus: Any, config: dict[str, Any]) -> Node:
    return DyingNode(bus=bus, **config)


# ── manifest ───────────────────────────────────────────────────────


_GOOD_MANIFEST = """
[app]
name = "conftest-app"
version = "0.0.1"
requires_framework = ">=0.1"
mode = "fused"
event_loop = "none"
single_instance = true

[bus]
backend = "inproc"

[[node]]
id = "ticker"
tier = 3
backend = "thread"
factory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"
restart = "never"
config_key = "ticker"
"""


def _write_app(tmp_path: pathlib.Path, manifest: str = _GOOD_MANIFEST,
               config: str = "ticker:\n  tick_interval_s: 0.01\n") -> pathlib.Path:
    (tmp_path / "jaeger.toml").write_text(manifest, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(config, encoding="utf-8")
    return tmp_path


def test_manifest_happy_path(tmp_path):
    spec = load_manifest(_write_app(tmp_path))
    assert spec.name == "conftest-app"
    assert spec.bus.backend == "inproc"
    assert spec.nodes[0].id == "ticker"
    assert spec.nodes[0].restart == "never"


def test_manifest_refuses_unknown_keys(tmp_path):
    bad = _GOOD_MANIFEST.replace('mode = "fused"', 'modee = "fused"')
    with pytest.raises(ValueError, match="modee"):
        load_manifest(_write_app(tmp_path, bad))


def test_manifest_refuses_bad_enums(tmp_path):
    bad = _GOOD_MANIFEST.replace('backend = "thread"',
                                 'backend = "hovercraft"')
    with pytest.raises(ValueError, match="hovercraft"):
        load_manifest(_write_app(tmp_path, bad))


def test_manifest_refuses_thread_without_factory(tmp_path):
    bad = _GOOD_MANIFEST.replace(
        'factory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"', 'factory = ""')
    with pytest.raises(ValueError, match="needs `factory`"):
        load_manifest(_write_app(tmp_path, bad))


# ── M2a: slot-resolution (manifest binds a node by slot, not factory) ──


def test_manifest_parses_node_slot(tmp_path):
    """A ``[[node]]`` may declare ``slot=`` with no ``factory=`` — the
    thread-backend rule now accepts factory OR slot."""
    m = _GOOD_MANIFEST.replace(
        'factory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"',
        'slot = "widgets"')
    spec = load_manifest(_write_app(tmp_path, m))
    assert spec.nodes[0].slot == "widgets"
    assert spec.nodes[0].factory == ""


def test_manifest_refuses_thread_without_factory_or_slot(tmp_path):
    bad = _GOOD_MANIFEST.replace(
        'factory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"', 'factory = ""')
    with pytest.raises(ValueError, match="needs `factory` or `slot`"):
        load_manifest(_write_app(tmp_path, bad))


def test_manifest_unknown_keys_still_refused_with_slot_present(tmp_path):
    """``slot`` is now an allowed key — a genuinely unknown key next to
    it still refuses (the allowlist add didn't loosen anything else)."""
    m = _GOOD_MANIFEST.replace(
        'factory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"',
        'slot = "widgets"\nbogus_key = "x"')
    with pytest.raises(ValueError, match="bogus_key"):
        load_manifest(_write_app(tmp_path, m))


def test_manifest_refuses_subprocess_on_inproc_bus(tmp_path):
    bad = _GOOD_MANIFEST.replace(
        'backend = "thread"\nfactory = "dev.tests.jaeger_os.app.test_app_format:make_ticker"',
        'backend = "subprocess"\nmodule = "dev.tests.jaeger_os.app._worker_node"',
    )
    with pytest.raises(ValueError, match="zmq"):
        load_manifest(_write_app(tmp_path, bad))


def test_manifest_refuses_future_format(tmp_path):
    bad = _GOOD_MANIFEST.replace('">=0.1"', '">=99.0"')
    with pytest.raises(RuntimeError, match="refusing to boot"):
        load_manifest(_write_app(tmp_path, bad))
    assert FRAMEWORK_FORMAT == "0.1"


def test_manifest_refuses_two_main_surfaces(tmp_path):
    bad = _GOOD_MANIFEST + (
        '\n[[surface]]\nid = "a"\nmain = true\nfactory = "x:y"\n'
        '\n[[surface]]\nid = "b"\nmain = true\nfactory = "x:y"\n'
    )
    with pytest.raises(ValueError, match="at most one main"):
        load_manifest(_write_app(tmp_path, bad))


def test_manifest_qt_requires_a_main_surface(tmp_path):
    bad = _GOOD_MANIFEST.replace('event_loop = "none"',
                                 'event_loop = "qt"')
    with pytest.raises(ValueError, match="main surface"):
        load_manifest(_write_app(tmp_path, bad))


# ── config ─────────────────────────────────────────────────────────


def test_config_refuses_non_mapping(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_config(p)


def test_config_slices(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("ticker:\n  rate: 5\n", encoding="utf-8")
    cfg = load_config(p)
    assert slice_for(cfg, "ticker") == {"rate": 5}
    assert slice_for(cfg, "absent") == {}
    assert slice_for(cfg, "") == {}


# ── bus (inproc) ─────────────────────────────────────────────────────
#
# MessageRegistry/RawMessage were the ZMQ wire-decode registry (0.8 U1
# deleted app/bus/ + the chassis-ZMQ path); the in-process bus is a
# pass-through — it never needs a registry, it just delivers whatever
# dataclass you published. These two tests now prove exactly that: a
# real publish -> subscribe delivery of a plain dataclass message.


def test_inproc_bus_delivers_plain_dataclass_messages_untouched():
    bus = InProcBus()
    try:
        got: list[Any] = []
        bus.subscribe("/test/ping", got.append)
        msg = Ping(n=7)
        bus.publish(msg)
        assert _wait_for(lambda: got)
        assert got[0] is msg and got[0].n == 7   # object passed through, not re-decoded
    finally:
        bus.close()


def test_inproc_bus_routes_and_isolates_bad_subscribers():
    bus = InProcBus()
    try:
        got: list[Any] = []
        bus.subscribe("/test/ping", lambda m: 1 / 0)
        bus.subscribe("/test/ping", got.append)
        bus.publish(Ping(n=1))
        assert _wait_for(lambda: got)
        assert got[0].n == 1
    finally:
        bus.close()
        bus.close()   # idempotent


# ── node lifecycle ─────────────────────────────────────────────────


def test_node_lifecycle_and_fatal_setup():
    bus = InProcBus()
    try:
        node = TickerNode(bus=bus)
        import threading
        t = threading.Thread(target=node.run, daemon=True)
        t.start()
        assert _wait_for(lambda: node.ticks >= 3)
        assert node.state == NodeState.RUNNING
        node.stop()
        t.join(timeout=2.0)
        assert node.state == NodeState.STOPPED

        class Doomed(Node):
            def setup(self) -> None:
                raise RuntimeError("no device")

        torn = []
        doomed = Doomed(bus=bus)
        doomed.teardown = lambda: torn.append(1)  # type: ignore[method-assign]
        doomed.run()
        assert doomed.state == NodeState.FAILED
        assert torn == [1]
        assert "no device" in doomed.health()["error"]
    finally:
        bus.close()


def test_frame_node_update_render_split_and_pacing():
    class Blinker(FrameNode):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.updates = 0
            self.renders = 0

        def update_tick(self, ts: float) -> None:
            self.updates += 1

        def render_tick(self, ts: float) -> None:
            self.renders += 1

    bus = InProcBus()
    try:
        node = Blinker(bus=bus, fps=50, name="blinker")
        import threading
        t = threading.Thread(target=node.run, daemon=True)
        start = time.monotonic()
        t.start()
        assert _wait_for(lambda: node.frames_rendered >= 10)
        elapsed = time.monotonic() - start
        node.stop()
        t.join(timeout=2.0)
        assert node.updates == node.renders == node.frames_rendered
        # 10 frames at 50 fps ≈ 0.2 s — generous bounds, but it must
        # be PACED, not a busy loop.
        assert 0.1 < elapsed < 2.0
        assert node.health()["fps_target"] == 50.0
    finally:
        bus.close()


def test_app_node_is_the_real_nodes_base_node():
    """0.8 U2: the chassis's Node/NodeState/FrameNode were a
    strict-subset duplicate of the real ``jaeger_os.nodes.base``
    classes (app/node.py). That duality is gone — there is exactly
    one Node, one NodeState, one FrameNode, and ``jaeger_os.app`` just
    re-exports them."""
    assert app_pkg.Node is nodes_base_mod.Node
    assert app_pkg.NodeState is nodes_base_mod.NodeState
    assert app_pkg.FrameNode is nodes_base_mod.FrameNode
    assert Node is nodes_base_mod.Node
    assert NodeState is nodes_base_mod.NodeState
    assert FrameNode is nodes_base_mod.FrameNode


def test_frame_node_tick_increments_frames_rendered():
    """FrameNode, moved into nodes/base.py, still runs a real
    update/render tick loop against a real bus."""
    class Blinker(nodes_base_mod.FrameNode):
        def render_tick(self, ts: float) -> None:
            pass

    bus = InProcBus()
    try:
        node = Blinker(bus=bus, fps=50, name="blinker")
        import threading
        t = threading.Thread(target=node.run, daemon=True)
        t.start()
        assert _wait_for(lambda: node.frames_rendered >= 2)
        node.stop()
        t.join(timeout=2.0)
    finally:
        bus.close()


# ── supervisor: thread backend + restart policy ────────────────────


def test_thread_handle_restart_makes_fresh_instance():
    bus = InProcBus()
    try:
        spec = NodeSpec(id="ticker", factory="x:y")
        handle = ThreadHandle(spec, lambda: TickerNode(bus=bus))
        handle.start()
        assert _wait_for(handle.alive)
        first = handle.node()
        handle.restart()
        assert _wait_for(handle.alive)
        assert handle.node() is not first
        assert handle.restarts == 1
        handle.stop()
        assert not handle.alive()
        assert handle.state() == "off"
    finally:
        bus.close()


def test_supervisor_on_failure_restarts_with_backoff(monkeypatch):
    monkeypatch.setattr(supervisor_mod, "_BACKOFF_BASE_S", 0.05)
    monkeypatch.setattr(supervisor_mod, "_BACKOFF_CAP_S", 0.1)
    bus = InProcBus()
    sup = Supervisor(bus=bus)
    try:
        spec = NodeSpec(id="dying", factory="x:y", restart="on_failure")
        handle = ThreadHandle(spec, lambda: DyingNode(bus=bus))
        sup.add(handle)
        sup.start_all()
        assert _wait_for(lambda: handle.restarts >= 2, timeout_s=5.0)
    finally:
        sup.stop_all()
        bus.close()


def test_supervisor_burst_limit_gives_up(monkeypatch):
    monkeypatch.setattr(supervisor_mod, "_BACKOFF_BASE_S", 0.02)
    monkeypatch.setattr(supervisor_mod, "_BACKOFF_CAP_S", 0.02)
    monkeypatch.setattr(supervisor_mod, "_BURST_LIMIT", 3)
    bus = InProcBus()
    sup = Supervisor(bus=bus)
    try:
        spec = NodeSpec(id="dying", factory="x:y", restart="on_failure")
        handle = ThreadHandle(spec, lambda: DyingNode(bus=bus))
        sup.add(handle)
        sup.start_all()
        assert _wait_for(lambda: not handle.intent_running, timeout_s=5.0)
        diag = sup.diagnose("dying")
        assert diag["crash_loop"] is True
        assert "giving up" in diag["last_error"]
    finally:
        sup.stop_all()
        bus.close()


def test_supervisor_never_policy_stays_down():
    bus = InProcBus()
    sup = Supervisor(bus=bus)
    try:
        spec = NodeSpec(id="dying", factory="x:y", restart="never")
        handle = ThreadHandle(spec, lambda: DyingNode(bus=bus))
        sup.add(handle)
        sup.start_all()
        assert _wait_for(lambda: not handle.alive())
        time.sleep(0.3)
        assert handle.restarts == 0
    finally:
        sup.stop_all()
        bus.close()


# ── the chassis, headless ──────────────────────────────────────────


def test_app_boots_runs_verbs_and_shuts_down(tmp_path):
    app = JaegerApp(_write_app(tmp_path)).boot()
    try:
        rows = app.supervisor.ls()
        assert rows[0]["id"] == "ticker"
        assert _wait_for(
            lambda: app.supervisor.ls()[0]["state"] == "running")
        app.supervisor.stop("ticker")
        assert app.supervisor.ls()[0]["state"] == "off"
        app.supervisor.start("ticker")
        assert _wait_for(
            lambda: app.supervisor.ls()[0]["state"] == "running")
        app.supervisor.restart("ticker")
        diag = app.supervisor.diagnose("ticker")
        assert diag["restarts"] == 1 and diag["crash_loop"] is False
    finally:
        app.shutdown()
        app.shutdown()   # idempotent
    assert not (tmp_path / ".run" / "conftest-app.pid").exists()


def test_boot_injects_bus_into_node_runtime_singleton(tmp_path):
    """0.8 U3: JaegerApp._build_bus injects ``self.bus`` into
    ``jaeger_os.nodes.runtime`` so ``ensure_tts_node`` / the windowed
    app's AgentBridge share ONE bus instead of two disconnected
    InProcBus instances (the pre-U3 windowed-app duality)."""
    from jaeger_os.nodes import runtime as node_runtime

    node_runtime.shutdown()   # start from a clean singleton
    app = JaegerApp(_write_app(tmp_path)).boot()
    try:
        assert node_runtime.get_bus() is app.bus
    finally:
        app.shutdown()
        node_runtime.shutdown()   # reset singleton for later tests


# ── supervisor-backed ensure_* delegation (0.8 U3b) ─────────────────
#
# Uses the REAL "animation" node factory (jaeger_os.nodes.animation:
# make_animation_node) — it's the lightweight one of the three
# graduated nodes (no LLM/Whisper/mic hardware); enable_bridge=false
# in config keeps it from binding a real WebSocket port in CI. The
# unit-level fake-supervisor tests in dev/tests/jaeger_os/nodes/
# test_runtime.py cover the "no supervisor" / "undeclared" /
# "disabled" fallback branches; these two exercise the REAL
# Supervisor + ThreadHandle end to end.

_ANIMATION_APP_MANIFEST = """
[app]
name = "conftest-animation-app"
version = "0.0.1"
requires_framework = ">=0.1"
mode = "fused"
event_loop = "none"
single_instance = false

[bus]
backend = "inproc"

[[node]]
id = "animation"
tier = 3
backend = "thread"
slot = "animation"
restart = "on_failure"
config_key = "avatar"
"""


def _write_animation_app(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "jaeger.toml").write_text(
        _ANIMATION_APP_MANIFEST, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        "avatar:\n  enable_bridge: false\n", encoding="utf-8")
    return tmp_path


def test_supervisor_backed_ensure_animation_node_returns_supervisor_object(
    tmp_path,
):
    """The manifest-declared "animation" node is supervisor-owned —
    ``ensure_animation_node()`` (still what the agent's avatar tools
    call) must delegate to the SAME live node the supervisor manages,
    not spawn a second thread (the pre-U3b reason these nodes stayed
    disabled — see jaeger.toml's header)."""
    from jaeger_os.nodes import runtime as node_runtime

    node_runtime.shutdown()
    app = JaegerApp(_write_animation_app(tmp_path)).boot()
    try:
        assert _wait_for(
            lambda: app.supervisor.ls()[0]["state"] == "running")
        supervised_node = app.supervisor.node("animation")
        assert supervised_node is not None

        ensured_node = node_runtime.ensure_animation_node()
        assert ensured_node is supervised_node   # no double-spawn
        assert node_runtime._animation_node is supervised_node
    finally:
        app.shutdown()
        node_runtime.shutdown()


def test_supervisor_backed_ensure_animation_node_reflects_restart(tmp_path):
    """The new seam this delegation adds: a supervisor-driven restart
    produces a FRESH AnimationNode object (ThreadHandle.restart()'s
    "never reuse a torn-down node object" contract) —
    ``ensure_animation_node()`` must track the NEW object, not a
    cached-stale one (``get_synth``/``get_audio_session`` depend on
    the equivalent for tts/audio_session)."""
    from jaeger_os.nodes import runtime as node_runtime

    node_runtime.shutdown()
    app = JaegerApp(_write_animation_app(tmp_path)).boot()
    try:
        assert _wait_for(
            lambda: app.supervisor.ls()[0]["state"] == "running")
        node1 = node_runtime.ensure_animation_node()

        app.supervisor.restart("animation")
        assert _wait_for(
            lambda: app.supervisor.ls()[0]["state"] == "running")

        node2 = node_runtime.ensure_animation_node()
        assert node2 is not node1
        assert node2 is app.supervisor.node("animation")
    finally:
        app.shutdown()
        node_runtime.shutdown()


def test_animation_config_key_avatar_routes_bridge_port_to_the_factory(
    tmp_path, monkeypatch,
):
    """0.8 M2c: the manifests' animation node used to declare
    ``config_key = "animation"`` — a key matching no field on
    ``Config`` (``AvatarConfig`` lives at ``Config.avatar``), so a real
    instance config.yaml's ``avatar:`` section (bridge_host/bridge_port)
    could never reach ``make_animation_node`` through this chassis path.
    Fixed to ``config_key = "avatar"``. This proves the full chain —
    manifest -> ``_make_handle`` -> ``slice_for`` -> the factory ``fn``
    ``ThreadHandle`` invokes -> ``_build_animation_node`` — actually
    honors a custom ``bridge_port`` from the node's config slice, without
    binding a real socket (``FrameBridge`` itself is faked so
    ``enable_bridge: true`` is safe here)."""
    from jaeger_os.nodes import runtime as node_runtime

    captured: dict[str, Any] = {}

    class _FakeBridge:
        def __init__(self, *, host: str = "127.0.0.1", port: int = 8765,
                     path: str = "/frames") -> None:
            captured["host"] = host
            captured["port"] = port

        def start(self, *, ready_timeout_s: float = 5.0) -> None:
            pass

        def stop(self, *, timeout_s: float = 5.0) -> None:
            pass

        def publish_frame(self, frame: Any) -> None:
            pass

    monkeypatch.setattr(node_runtime.animation_bridge, "FrameBridge", _FakeBridge)

    (tmp_path / "jaeger.toml").write_text(
        _ANIMATION_APP_MANIFEST, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        "avatar:\n  bridge_host: 0.0.0.0\n  bridge_port: 9911\n"
        "  enable_bridge: true\n",
        encoding="utf-8",
    )

    node_runtime.shutdown()
    app = JaegerApp(tmp_path).boot()
    try:
        assert _wait_for(
            lambda: app.supervisor.ls()[0]["state"] == "running")
        assert captured == {"host": "0.0.0.0", "port": 9911}
    finally:
        app.shutdown()
        node_runtime.shutdown()


# ── M2a: slot-resolution end to end (app._make_handle → discover_modules) ──


_SLOT_APP_MANIFEST = """
[app]
name = "conftest-slot-app"
version = "0.0.1"
requires_framework = ">=0.1"
mode = "fused"
event_loop = "none"
single_instance = false

[bus]
backend = "inproc"

[[node]]
id = "widget"
tier = 3
backend = "thread"
slot = "widgets"
restart = "never"
config_key = "widget"
"""


def _write_slot_app(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "jaeger.toml").write_text(_SLOT_APP_MANIFEST, encoding="utf-8")
    (tmp_path / "config.yaml").write_text("widget: {}\n", encoding="utf-8")
    return tmp_path


def test_slot_bound_node_resolves_factory_and_boots(tmp_path, monkeypatch):
    """A ``[[node]]`` declaring only ``slot=`` gets its ``factory``
    populated from ``discover_modules()`` before ``resolve_ref`` runs,
    and boots under the supervisor exactly like a factory-string node."""
    from jaeger_os.core import modules as modules_mod

    fake_spec = modules_mod.ModuleSpec(
        module="widget_engine", slot="widgets",
        factory=f"{__name__}:make_ticker",
    )
    monkeypatch.setattr(
        modules_mod, "discover_modules", lambda root=None: {
            "widgets": [fake_spec]})

    app = JaegerApp(_write_slot_app(tmp_path)).boot()
    try:
        node_spec = next(n for n in app.spec.nodes if n.id == "widget")
        assert node_spec.factory == f"{__name__}:make_ticker"   # populated
        assert _wait_for(
            lambda: app.supervisor.ls()[0]["state"] == "running")
    finally:
        app.shutdown()


def test_slot_bound_node_picks_deterministically_when_multiple_modules(
    tmp_path, monkeypatch,
):
    """More than one module for a slot: pick sorted-by-module-name first,
    not whichever discover_modules happened to return first."""
    from jaeger_os.core import modules as modules_mod

    zeta = modules_mod.ModuleSpec(
        module="zeta_engine", slot="widgets", factory=f"{__name__}:missing")
    alpha = modules_mod.ModuleSpec(
        module="alpha_engine", slot="widgets", factory=f"{__name__}:make_ticker")
    monkeypatch.setattr(
        modules_mod, "discover_modules", lambda root=None: {
            "widgets": [zeta, alpha]})

    app = JaegerApp(_write_slot_app(tmp_path)).boot()
    try:
        node_spec = next(n for n in app.spec.nodes if n.id == "widget")
        assert node_spec.factory == f"{__name__}:make_ticker"   # alpha, not zeta
    finally:
        app.shutdown()


def test_slot_bound_node_unknown_slot_raises_naming_the_slot(tmp_path, monkeypatch):
    """Zero modules for the declared slot is fail-closed — a declared
    node must resolve, never silently vanish."""
    from jaeger_os.core import modules as modules_mod

    monkeypatch.setattr(modules_mod, "discover_modules", lambda root=None: {})

    with pytest.raises(ValueError, match="widgets"):
        JaegerApp(_write_slot_app(tmp_path)).boot()


def test_slot_bound_tts_node_resolves_to_kokoro_via_real_discovery(tmp_path):
    """No monkeypatching: the REAL ``discover_modules()`` walking the
    REAL ``jaeger_os/nodes/`` tree resolves ``slot = "tts"`` to
    kokoro_tts's factory and boots it under the supervisor — the exact
    path ``jaeger.windowed.toml``'s tts node now takes."""
    manifest = """
[app]
name = "conftest-tts-slot-app"
requires_framework = ">=0.1"
event_loop = "none"
single_instance = false

[bus]
backend = "inproc"

[[node]]
id = "tts"
tier = 3
backend = "thread"
slot = "tts"
restart = "never"
config_key = "tts"
"""
    (tmp_path / "jaeger.toml").write_text(manifest, encoding="utf-8")
    (tmp_path / "config.yaml").write_text("tts: {}\n", encoding="utf-8")

    from jaeger_os.nodes import runtime as node_runtime
    node_runtime.shutdown()
    app = JaegerApp(tmp_path).boot()
    try:
        node_spec = next(n for n in app.spec.nodes if n.id == "tts")
        assert node_spec.factory == "jaeger_os.nodes.kokoro_tts:make_tts_node"
        assert _wait_for(
            lambda: app.supervisor.ls()[0]["state"] == "running")
    finally:
        app.shutdown()
        node_runtime.shutdown()


def test_second_instance_refused(tmp_path):
    root = _write_app(tmp_path)
    app1 = JaegerApp(root).boot()
    try:
        with pytest.raises(SecondInstanceError, match="already running"):
            JaegerApp(root).boot()
    finally:
        app1.shutdown()
    # Slot released — a third boot succeeds.
    app3 = JaegerApp(root).boot()
    app3.shutdown()


def test_resolve_ref_contract():
    # __name__ keeps this self-aware: the test file lives at different
    # paths in different apps that adopt the format (dev/tests/... in
    # JROS, tests/ in the demo, etc.), and pytest may import it under
    # its short name depending on rootdir discovery. Either way,
    # resolve_ref("<this module>:make_ticker") returns this very fn.
    assert resolve_ref(f"{__name__}:make_ticker") is make_ticker
    with pytest.raises(ValueError, match="module:attr"):
        resolve_ref("no_colon")
    with pytest.raises(ImportError, match="no attribute"):
        resolve_ref(f"{__name__}:missing")


# ── no-orphans: reap_stale ─────────────────────────────────────────


def test_reap_stale_kills_leftover_children(tmp_path):
    child = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(60)"])
    registry = tmp_path / "children.json"
    registry.write_text(f'{{"{child.pid}": "leftover"}}', encoding="utf-8")
    try:
        reaped = reap_stale(registry)
        assert child.pid in reaped
        assert _wait_for(lambda: child.poll() is not None)
    finally:
        if child.poll() is None:
            child.kill()


# NOTE (0.8 U1): the subprocess-backend + chassis-ZMQ end-to-end test
# that lived here (spawning a real subprocess node wired over
# jaeger_os.app.bus.zmq.Broker/ZmqBus + app.child.child_main) was
# removed along with app/bus/ and app/child.py. That path was never
# exercised in production — both shipped manifests run
# `[bus] backend = "inproc"`, and no manifest in this repo ever
# configured a subprocess node — so the test now exercised only
# dropped code. Its fixture module
# (dev/tests/jaeger_os/app/_worker_node.py) is deleted too. Repointing
# it onto transport's ZMQBus instead of deleting it would need
# NodeHealth/LogLine (and the worker's TestCmd/TestEcho) converted to
# msgspec Structs registered in transport.topics — out of scope here
# (U1 keeps the message dataclasses plain; msgspec conversion is later,
# alongside the Transcript/NodeHealth overlap noted for U3).
# `test_manifest_refuses_subprocess_on_inproc_bus` above still covers
# the manifest-validation half (subprocess needs backend="zmq") since
# that logic lives in manifest.py, untouched by this change.


def test_node_health_message_shape():
    """Canon NodeHealth (0.8 U3): ``transport.topics`` msgspec Struct on
    ``/sense/node_health``. The plain-dataclass twin that used to live
    in ``app/health.py`` (on the different, unpublished ``/sys/node_health``
    topic) is gone — every ``nodes.base.Node`` now heartbeats this type."""
    h = topics.NodeHealth(node="x", state="running", detail="ok")
    assert h.topic == "/sense/node_health"
    assert h.node == "x" and h.state == "running" and h.detail == "ok"


def test_health_cache_receives_a_real_base_node_heartbeat():
    """0.8 U3: every ``nodes.base.Node`` heartbeats ``topics.NodeHealth``
    on ``/sense/node_health`` from inside its OWN ``run()`` loop —
    HealthCache (subscribed there) must observe it from a REAL node on a
    REAL InProcBus, no mocking of either side."""
    bus = InProcBus()
    cache = HealthCache(bus)
    node = TickerNode(bus=bus)
    import threading
    t = threading.Thread(target=node.run, daemon=True)
    t.start()
    try:
        assert _wait_for(lambda: cache.latest(node.name) is not None,
                          timeout_s=3.0)
        latest = cache.latest(node.name)
        assert latest.state == "running"
        assert latest.topic == "/sense/node_health"
        age = cache.age_s(node.name)
        assert age is not None and age >= 0.0
    finally:
        node.stop()
        t.join(timeout=2.0)
        bus.close()


# ── core (Tier-1 host role) ────────────────────────────────────────

@dataclasses.dataclass
class _NodeUp:
    """Published by the order-node in ITS setup. The core receives it
    only if the core's subscription already existed — i.e. the core set
    up BEFORE the node did. This is the identity-stable boot-order probe
    (a shared module global can't cross the factory-import boundary:
    pytest collects this file as ``app.test_app_format`` while the
    manifest factory ref imports ``dev.tests.jaeger_os.app...`` — two
    module objects, two globals)."""
    topic: str = "/sense/node_up"


class _ProbeCore(Core):
    def __init__(self, *, bus: Any, **_: Any) -> None:
        super().__init__(bus=bus)            # asserts the OS main thread
        self.setup_called = False
        self.stop_called = False
        self.setup_on_main_thread = False
        self.saw_node_setup = False

    def setup(self) -> None:
        import threading
        self.setup_called = True
        self.setup_on_main_thread = (
            threading.current_thread() is threading.main_thread())
        # subscribe on the MAIN thread, during init_core (before nodes)
        self.bus.subscribe("/sense/node_up", self._on_node_up)

    def _on_node_up(self, msg: Any) -> None:
        self.saw_node_setup = True

    def stop(self) -> None:
        self.stop_called = True


def make_probe_core(bus: Any, config: dict[str, Any]) -> _ProbeCore:
    return _ProbeCore(bus=bus, **config)


class _OrderNode(Node):
    def __init__(self, *, bus: Any, **_: Any) -> None:
        super().__init__(bus=bus, name="order-node", tick_interval_s=0.01)

    def setup(self) -> None:
        self.bus.publish(_NodeUp())


def make_order_node(bus: Any, config: dict[str, Any]) -> Node:
    return _OrderNode(bus=bus, **config)


_CORE_MANIFEST = """
[app]
name = "core-app"
requires_framework = ">=0.1"
event_loop = "none"

[bus]
backend = "inproc"

[core]
factory = "dev.tests.jaeger_os.app.test_app_format:make_probe_core"

[[node]]
id = "order-node"
tier = 3
backend = "thread"
factory = "dev.tests.jaeger_os.app.test_app_format:make_order_node"
restart = "never"
"""


def test_manifest_parses_core(tmp_path):
    spec = load_manifest(_write_app(tmp_path, _CORE_MANIFEST))
    assert spec.core.factory == (
        "dev.tests.jaeger_os.app.test_app_format:make_probe_core")
    assert spec.core.enabled is True


def test_manifest_refuses_enabled_core_without_factory(tmp_path):
    bad = _CORE_MANIFEST.replace(
        'factory = "dev.tests.jaeger_os.app.test_app_format:make_probe_core"',
        "enabled = true")
    with pytest.raises(ValueError, match="core.*needs"):
        load_manifest(_write_app(tmp_path, bad))


def test_core_constructed_off_main_thread_raises():
    import threading
    bus = InProcBus()
    errs: list[Exception] = []

    def build():
        try:
            _ProbeCore(bus=bus)
        except CoreMainThreadError as exc:
            errs.append(exc)

    t = threading.Thread(target=build)
    t.start()
    t.join()
    assert errs and isinstance(errs[0], CoreMainThreadError)
    assert isinstance(_ProbeCore(bus=bus), Core)   # main thread: fine
    bus.close()


def test_core_inits_on_main_thread_before_nodes_and_is_not_supervised(tmp_path):
    app = JaegerApp(_write_app(tmp_path, _CORE_MANIFEST)).boot()
    try:
        # built by the chassis, setup run on the OS main thread
        assert app.core is not None and app.core.setup_called
        assert app.core.setup_on_main_thread is True
        # boot order: the core received the order-node's /sense/node_up,
        # which is only possible if the core subscribed (in init_core)
        # BEFORE the node published (in start_nodes) — core before nodes
        assert _wait_for(lambda: app.core.saw_node_setup)
        # the core is NOT a supervised node
        node_ids = {row["id"] for row in app.supervisor.ls()}
        assert "order-node" in node_ids
        assert "core" not in node_ids and "core-app" not in node_ids
    finally:
        app.shutdown()
    assert app.core.stop_called   # stop ran on shutdown, before bus close
