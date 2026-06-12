"""JP01 package boot — topology → links → adapters → nodes → tools.

``load(bus=…)`` is the one entry point (the generic
``jaeger_os.hardware.boot.boot_hardware`` resolves it by convention).
It is idempotent per process and returns a :class:`Jp01Runtime`:

  * every enabled controller gets its adapter + Link (simulated
    controllers get the adapter module's firmware-shaped
    ``simulator()`` behind a MockTransport);
  * mc01's L1 stop registers on the :class:`EStopLatch`;
  * with a bus: the stock ``MotorNode``/``LightNode`` run on daemon
    threads (the same node formation CC01 mirrors), and a 1 s
    heartbeat thread publishes ``NodeHealth`` on
    ``/sense/node_health``;
  * capability umbrella tools (motion / lights / robot_vision /
    telemetry) register beta-gated.

``shutdown()`` tears down in reverse and is atexit-registered —
motors neutralized and LEDs blanked even on an unclean exit path.
"""

from __future__ import annotations

import pathlib
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import inspect

from jaeger_os import topics
from jaeger_os.agent.schemas.tool_registry import unregister_tool
from jaeger_os.agent.schemas.tool_schema import ToolDef
from jaeger_os.hardware.capabilities import register_package_capabilities
from jaeger_os.hardware.link import Link
from jaeger_os.hardware.package import (
    ControllerSpec,
    PackageSpec,
    build_link,
    load_package,
    resolve_ref,
)
from jaeger_os.hardware.safety import EStopLatch

_PACKAGE_DIR = pathlib.Path(__file__).parent
_HEALTH_PERIOD_S = 1.0

_lock = threading.Lock()
_runtime: "Jp01Runtime | None" = None
_atexit_installed = False


@dataclass
class Jp01Runtime:
    spec: PackageSpec
    links: dict[str, Link]
    adapters: dict[str, Any]
    estop: EStopLatch
    tools: list[ToolDef]
    nodes: list[tuple[Any, threading.Thread]] = field(default_factory=list)
    bus: Any = None
    _health_stop: threading.Event = field(default_factory=threading.Event)
    _health_thread: threading.Thread | None = None

    def health(self) -> dict[str, Any]:
        return {
            name: adapter.telemetry()
            for name, adapter in self.adapters.items()
        } | {"estop": self.estop.status()}


def get_runtime() -> Jp01Runtime | None:
    return _runtime


def adapter_for(controller: str) -> Any:
    """Capability handlers' registry lookup. Raises while unbooted —
    the umbrella dispatcher turns that into a typed error."""
    rt = _runtime
    if rt is None:
        raise ConnectionError("jp01 package not booted")
    try:
        return rt.adapters[controller]
    except KeyError:
        raise ConnectionError(f"no adapter for controller {controller!r}") from None


def _build_adapter(ctrl: ControllerSpec, *, package: str) -> Any:
    """Instantiate the topology's ``adapter:`` ref — the declared
    class IS the wired class (no parallel hardcoded map; the old
    CC01 ``enabled_plugins``-declared-but-unread pattern is exactly
    what this framework exists to kill). Adapters taking a
    ``streams`` kwarg get the controller's stream directory."""
    cls = resolve_ref(ctrl.adapter, package=package)
    kwargs: dict[str, Any] = {}
    if "streams" in inspect.signature(cls).parameters and ctrl.streams:
        kwargs["streams"] = ctrl.streams
    return cls(**kwargs)


def _sim_responder(ctrl: ControllerSpec, *, package: str) -> Any:
    """The adapter module's ``simulator()`` responder, when it ships
    one. A simulated controller without a simulator still boots —
    MockTransport just swallows writes silently."""
    mod_path = ctrl.adapter.partition(":")[0]
    try:
        factory = resolve_ref(f"{mod_path}:simulator", package=package)
    except ImportError:
        return None
    return factory()


def load(*, bus: Any = None) -> Jp01Runtime:
    """Boot (or return the already-booted) JP01 runtime."""
    global _runtime, _atexit_installed
    with _lock:
        if _runtime is not None:
            return _runtime

        spec = load_package(_PACKAGE_DIR)

        if spec.safety and spec.safety.firmware_watchdog_required:
            simulated = all(
                c.simulated for c in spec.controllers.values()
            )
            if not simulated:
                print(
                    "[jp01] WARNING: MC01 has no L0 firmware watchdog — "
                    "live motion capabilities must stay beta until it "
                    "ships (plan §2.8)",
                    file=sys.stderr, flush=True,
                )

        links: dict[str, Link] = {}
        adapters: dict[str, Any] = {}
        for name, ctrl in spec.controllers.items():
            if not ctrl.enabled:
                continue
            adapter = _build_adapter(ctrl, package=spec.package)
            link = build_link(
                name, ctrl,
                on_event=adapter.on_wire_event,
                mock_responder=(
                    _sim_responder(ctrl, package=spec.package)
                    if ctrl.simulated else None
                ),
            )
            adapter.attach_link(link)
            links[name] = link
            adapters[name] = adapter

        estop = EStopLatch(bus)
        if "mc01" in adapters:
            estop.register_stop("mc01", adapters["mc01"].estop)

        runtime = Jp01Runtime(
            spec=spec, links=links, adapters=adapters,
            estop=estop, tools=[], bus=bus,
        )

        # Nodes own their adapters' lifecycle (node.setup() calls
        # adapter.start()); boot directly starts only the adapters no
        # node covers. Either way a dead controller degrades (tools
        # fail closed via check_fn) — it never blocks boot.
        node_managed: set[str] = set()
        if bus is not None:
            node_managed = _start_nodes(runtime, bus)
            _start_health_heartbeat(runtime, bus)
        for name, adapter in adapters.items():
            if name in node_managed:
                continue
            try:
                adapter.start()
            except Exception as exc:  # noqa: BLE001
                print(f"[jp01] {name} link failed: {exc} — degraded",
                      file=sys.stderr, flush=True)

        runtime.tools = register_package_capabilities(
            spec, links=links, estop=estop,
        )

        _runtime = runtime
        if not _atexit_installed:
            import atexit
            atexit.register(shutdown)
            _atexit_installed = True
        print(
            f"[jp01] booted ({'sim' if all(c.simulated for c in spec.controllers.values()) else 'LIVE'}): "
            f"controllers={sorted(adapters)} "
            f"tools={sorted(t.name for t in runtime.tools)} (beta-gated)",
            flush=True,
        )
        return runtime


def _start_nodes(runtime: Jp01Runtime, bus: Any) -> set[str]:
    """Run the stock generic nodes over the JP01 adapters — the node
    formation. Vision stays adapter-only until live streams land.
    Returns the controllers whose adapters the nodes now own."""
    from jaeger_os.nodes.base import NodeState
    from jaeger_os.nodes.light import LightNode
    from jaeger_os.nodes.motor import MotorNode

    specs: list[tuple[str, Any]] = []
    if "mc01" in runtime.adapters:
        specs.append(("mc01", MotorNode(
            bus=bus, adapter=runtime.adapters["mc01"],
            name="jp01-motor", install_signal_handlers=False,
        )))
    if "avc01" in runtime.adapters:
        specs.append(("avc01", LightNode(
            bus=bus, adapter=runtime.adapters["avc01"],
            name="jp01-light", install_signal_handlers=False,
        )))
    managed: set[str] = set()
    for controller, node in specs:
        thread = threading.Thread(
            target=node.run, name=f"{node.name}-node", daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if node.state in (NodeState.RUNNING, NodeState.FAILED):
                break
            time.sleep(0.01)
        runtime.nodes.append((node, thread))
        if node.state == NodeState.RUNNING:
            managed.add(controller)
    return managed


def _start_health_heartbeat(runtime: Jp01Runtime, bus: Any) -> None:
    """1 s ``NodeHealth`` per controller — the supervisor-facing
    liveness surface (plan §2.7)."""

    def beat() -> None:
        while not runtime._health_stop.wait(_HEALTH_PERIOD_S):
            for name, adapter in runtime.adapters.items():
                try:
                    tel = adapter.telemetry()
                    link = runtime.links.get(name)
                    bus.publish(topics.NodeHealth(
                        node=f"jp01-{name}",
                        state="RUNNING",
                        link_connected=bool(link and link.connected),
                        last_controller_rx_age_s=float(
                            tel.get("heartbeat_age_s") or 0.0
                        ),
                        detail=tel.get("last_heartbeat", "")[:120],
                    ))
                except Exception:  # noqa: BLE001 — heartbeat never dies
                    pass

    runtime._health_thread = threading.Thread(
        target=beat, name="jp01-health", daemon=True,
    )
    runtime._health_thread.start()


def shutdown() -> None:
    """Reverse teardown. Idempotent; never raises."""
    global _runtime
    with _lock:
        runtime, _runtime = _runtime, None
    if runtime is None:
        return
    runtime._health_stop.set()
    if runtime._health_thread is not None:
        runtime._health_thread.join(timeout=2.0)
    for tool in runtime.tools:
        unregister_tool(tool.name)
    for node, thread in runtime.nodes:
        try:
            node.stop()
            thread.join(timeout=3.0)
        except Exception:  # noqa: BLE001
            pass
    # Nodes own their adapters' stop(); cover adapter-only controllers
    # (vcc01) and the no-bus path. Adapter.stop() is idempotent.
    for adapter in runtime.adapters.values():
        try:
            adapter.stop()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["Jp01Runtime", "load", "shutdown", "get_runtime", "adapter_for"]
