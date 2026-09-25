"""JaegerApp — the chassis. Every app boots the same way:

    manifest → instance slot → config → bus → nodes → surfaces → run
                                                                  ↓
                       teardown (reverse order, signal-safe, atexit)

Desktop-grade guarantees owned here (spec §checklist):
  * single instance — second launch refuses, with the running PID
    named (stale slots from crashed runs are reaped first);
  * no orphans — child PIDs are registered on disk at spawn; boot
    reaps a previous run's leftovers; shutdown walks live handles
    with terminate→kill, then surfaces close, then the bus;
  * one event loop — declared in the manifest (qt | none in format
    0.1; asyncio/tui reserved), owned by the main thread.
"""

from __future__ import annotations

import atexit
import importlib
import os
import pathlib
import signal
import sys
from typing import Any

from jaeger_os.app.catalog import BusCatalog
from jaeger_os.transport import Bus, InProcBus

from .config import load_config, slice_for
from .core import Core
from .health import HealthCache
from .logging import kv, log
from .manifest import AppSpec, NodeSpec, load_manifest
from .supervisor import (
    SubprocessHandle,
    Supervisor,
    ThreadHandle,
    reap_stale,
)
from .surfaces import SurfaceManager


def resolve_ref(ref: str) -> Any:
    """``"pkg.mod:attr"`` → the attribute. Loud on bad refs."""
    mod_path, _, attr = ref.partition(":")
    if not attr:
        raise ValueError(f"ref {ref!r} must be 'module:attr'")
    module = importlib.import_module(mod_path)
    try:
        return getattr(module, attr)
    except AttributeError:
        raise ImportError(f"{mod_path} has no attribute {attr!r}") from None


class SecondInstanceError(RuntimeError):
    """Another instance of this app already holds the slot."""


class JaegerApp:
    def __init__(
        self,
        manifest_path: str | pathlib.Path,
    ) -> None:
        # A file path is honored verbatim (an app may carry more than one
        # manifest — e.g. jaeger.sim.toml, jaeger.windowed.toml); a dir
        # path resolves to its default jaeger.toml. ``root`` is always the
        # containing directory (config + .run/ slot live there).
        manifest_path = pathlib.Path(manifest_path)
        self.root = (manifest_path.parent if manifest_path.is_file()
                     else manifest_path)
        self.spec: AppSpec = load_manifest(manifest_path)
        self.config: dict[str, Any] = {}
        self.bus: Bus | None = None
        self.health: HealthCache | None = None
        self.supervisor: Supervisor | None = None
        self.surfaces = SurfaceManager()
        self.core: Core | None = None
        self._broker: Any = None
        self._control: Any = None
        self.catalog: Any = None
        self._run_dir = self.root / ".run"
        self._slot_file = self._run_dir / f"{self.spec.name}.pid"
        self._registry_file = self._run_dir / f"{self.spec.name}.children.json"
        self._slot_held = False
        self._shutdown_done = False
        self._qt_app: Any = None

    # ── boot phases ──────────────────────────────────────────────

    def boot(self) -> "JaegerApp":
        """Phases 1-6. Separated from run() so headless tests can
        boot, poke, and shut down without an event loop."""
        self._acquire_instance()
        # Empty config = "" → "this app doesn't use a chassis-loaded
        # config" (JROS uses per-instance configs under sandbox/,
        # not a root-level config.yaml). Skip loading without falling
        # into root / "" → root/ → exists() → load_config(dir) → fail.
        if self.spec.inline_config:
            # [config.*] tables in jaeger.toml. One file, one format,
            # real types — TOML will not turn "NO" into False or eat a
            # digit off version 1.10 the way YAML does.
            self.config = self.spec.inline_config
        elif self.spec.config:
            cfg_path = self.root / self.spec.config
            self.config = load_config(cfg_path) if cfg_path.exists() else {}
        else:
            self.config = {}
        self._build_bus()
        self._log_boot_banner()
        self.health = HealthCache(self.bus)
        self.catalog = BusCatalog(self.bus).attach()
        self._init_core()
        self._start_nodes()
        self._start_control()
        self._install_signals()
        atexit.register(self.shutdown)
        self._log_startup_report()
        return self

    def run(self) -> int:
        """boot() + block on the manifest's event loop + teardown."""
        self.boot()
        try:
            if self.spec.event_loop == "qt":
                return self._run_qt()
            if self.spec.event_loop == "none":
                return 0   # caller drives (tests, scripts)
            raise ValueError(
                f"event_loop {self.spec.event_loop!r} not implemented "
                "in format 0.1 (qt | none)"
            )
        finally:
            if self.spec.event_loop != "none":
                self.shutdown()
        return 0

    def startup_report(self) -> list[str]:
        """What actually came up, one line per node.

        `--nodes` shows what WOULD run; this shows what DID, which is
        not the same thing — a node can be declared, resolved, started,
        and still fail its first tick. Borrowed from Quantum Codex,
        where it is the first thing an operator reads.

        Returned rather than printed so a surface or a test can use it.
        """
        lines = [f"{self.spec.name} {self.spec.version}"
                 f"   bus={self.spec.bus.backend}  mode={self.spec.mode}"]
        sup = self.supervisor
        for node in self.spec.nodes:
            if not node.enabled:
                if node.slot and not node.factory:
                    why = f"no module for slot {node.slot!r}"
                    if node.package:
                        why += f"  —  pip install {node.package}"
                else:
                    why = "disabled"
                lines.append(f"  [SKIP]  {node.id:16} — {why}")
                continue
            handle = sup._handles.get(node.id) if sup is not None else None
            if handle is None:
                lines.append(f"  [GONE]  {node.id:16} — never built")
                continue
            state = handle.state()
            source = node.factory.split(":")[0] or node.slot
            if handle.alive():
                tag = "[OK]" if state == "running" else "[UP]"
                lines.append(f"  {tag:7} {node.id:16} — {state}, {source}")
            else:
                err = (handle.last_error or "not running")
                lines.append(f"  [FAIL]  {node.id:16} — {err}")
        for surface in self.spec.surfaces:
            if surface.enabled:
                lines.append(f"  [OK]    {surface.id:16} — surface, "
                             f"{surface.factory}")
        return lines

    #: startup_report()'s own tag -> a log level. The report keeps its
    #: tags because surfaces and tests render it verbatim; the log gets
    #: the level instead, so an operator scanning a boot for red never
    #: has to read the text.
    _REPORT_LEVELS = {"[OK]": "ok", "[UP]": "ok", "[SKIP]": "warn",
                      "[FAIL]": "error", "[GONE]": "error"}

    def _log_boot_banner(self) -> None:
        """Who this app is — printed BEFORE the nodes come up.

        Every app on the chassis prints this, which is the point: a
        demo, a robot and a test all announce themselves the same way
        and none of them wrote the code to do it. It goes first because
        the reason you want it is to know what you are watching boot;
        printed after the node output it would be an epitaph.
        """
        import socket

        import jaeger_os

        name = self.spec.name
        log(name, f"booting jaeger app — {name}", level="boot", bus=self.bus)
        kv(name, "app", f"{name} {self.spec.version}", bus=self.bus)
        kv(name, "host", socket.gethostname(), bus=self.bus)
        kv(name, "framework", jaeger_os.__version__, bus=self.bus)
        kv(name, "bus", self.spec.bus.backend, bus=self.bus)
        kv(name, "mode", f"{self.spec.mode}, event_loop={self.spec.event_loop}",
           bus=self.bus)
        for node in self.spec.nodes:
            kv(name, node.id,
               f"tier {node.tier}  {node.factory or f'slot:{node.slot}'}"
               + ("" if node.enabled else "  (disabled)"), bus=self.bus)

    def _log_startup_report(self) -> None:
        """What actually came up — printed AFTER the nodes are started."""
        name = self.spec.name
        # [0] is the header line, already said by the boot banner's kv block.
        for line in self.startup_report()[1:]:
            tag, _, rest = line.strip().partition(" ")
            # The node id is padded inside `rest`, so dropping the tag
            # keeps the column: lstrip only eats the tag's own padding.
            log(name, rest.lstrip(),
                level=self._REPORT_LEVELS.get(tag, "info"), bus=self.bus)

        # NOT "ready": boot() returning means every node STARTED, which
        # is not the same as every node being usable — a TTS node with
        # `warm = true` is still loading weights on a background thread
        # right now. The chassis can only green-light its own job, so it
        # says what it actually knows.
        sup = self.supervisor
        running = sum(1 for n in self.spec.nodes if n.enabled
                      and sup is not None
                      and (h := sup._handles.get(n.id)) is not None
                      and h.alive())
        declared = sum(1 for n in self.spec.nodes if n.enabled)
        log(name, f"boot complete — {running}/{declared} nodes running",
            level="ok" if running == declared else "warn", bus=self.bus)

    def shutdown(self) -> None:
        """Reverse boot order. Idempotent; never raises; the
        windows-die-together + no-orphans moment."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        # First, so nothing new connects to a bus that is going away.
        try:
            from jaeger_os.transport import rendezvous
            rendezvous.withdraw(self.spec.name)
        except Exception:  # noqa: BLE001
            pass
        # Then the control plane, before the nodes it reports on start
        # disappearing — a `jaeger status` landing mid-teardown should
        # get "not running", not a half-dismantled answer. This was
        # never stopped at all: the thread is a daemon so the process
        # still exited, but the socket file was left behind every run.
        if self._control is not None:
            try:
                self._control.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.surfaces.close_all()
        except Exception:  # noqa: BLE001
            pass
        if self.supervisor is not None:
            self.supervisor.stop_all()
        # 0.8 U3b: clear the delegation target + tear down the
        # AnimationNode bridge/auto-driver sidecars the supervisor
        # doesn't know about (see runtime.set_supervisor's docstring).
        try:
            from jaeger_os.nodes import runtime as node_runtime
            node_runtime.set_supervisor(None)
        except Exception:  # noqa: BLE001
            pass
        if self.core is not None:
            try:
                self.core.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._broker is not None:
            try:
                self._broker.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:  # noqa: BLE001
                pass
        self._release_instance()
        try:
            from jaeger_os.core.modules import set_application_package
            set_application_package(None)
        except Exception:  # noqa: BLE001
            pass
        log(self.spec.name, "shutdown complete")

    # ── phase internals ──────────────────────────────────────────

    def _acquire_instance(self) -> None:
        if not self.spec.single_instance:
            return
        self._run_dir.mkdir(parents=True, exist_ok=True)
        if self._slot_file.exists():
            try:
                pid = int(self._slot_file.read_text().strip() or "0")
            except ValueError:
                pid = 0
            if pid and _pid_alive(pid):
                raise SecondInstanceError(
                    f"{self.spec.name} is already running (pid {pid}) — "
                    "quit it first (a second launch never doubles the app)"
                )
            # Stale slot from a crashed run: reap its children first.
            reap_stale(self._registry_file)
            # ...and the control socket the dead run could not unlink.
            # A clean exit removes its own (ControlServer.stop), but a
            # SIGKILL or a power cut never can — no process gets to run
            # code after SIGKILL. This is the only place that is SAFE
            # to do it: the pid above was just checked and is dead, so
            # the file cannot belong to a live app. Doing it in
            # ControlServer.start() instead would delete a LIVE peer's
            # socket and silently steal its endpoint.
            try:
                from jaeger_os.app.control import default_endpoint
                ep = default_endpoint(self.spec.name)
                if ep.startswith("ipc://"):
                    pathlib.Path(ep[len("ipc://"):]).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
        self._slot_file.write_text(str(os.getpid()), encoding="utf-8")
        self._slot_held = True

    def _release_instance(self) -> None:
        if self._slot_held:
            try:
                self._slot_file.unlink(missing_ok=True)
            except OSError:
                pass
            self._slot_held = False

    def _build_bus(self) -> None:
        """Build the bus the manifest asked for.

        ``inproc`` (default) — one process, one queue. Publishing passes
        REFERENCES, so a 3.6 MB frame costs nothing to hand around. This
        is the right default and most apps should never change it.

        ``zmq`` — a broker plus a connected bus, so nodes declared
        ``backend = "subprocess"`` can join from their own interpreter.
        Isolation costs serialization at the process boundary; it buys a
        node that cannot take the app down with it.

        Until 0.9 this ignored ``spec.bus.backend`` and always built an
        InProcBus, which made subprocess nodes unreachable: the manifest
        validator (correctly) refuses subprocess-on-inproc, and no
        manifest could produce anything else.
        """
        backend = (self.spec.bus.backend or "inproc").lower()
        if backend == "inproc":
            self.bus = InProcBus()
        elif backend == "zmq":
            from jaeger_os.transport.broker import (
                DEFAULT_XPUB_ENDPOINT, DEFAULT_XSUB_ENDPOINT, Broker,
                make_bus_for_node,
            )
            xsub = self.spec.bus.xsub or DEFAULT_XSUB_ENDPOINT
            xpub = self.spec.bus.xpub or DEFAULT_XPUB_ENDPOINT
            # The broker must be bound BEFORE anything connects — a
            # connect to an unbound endpoint silently no-ops and the
            # first publish is dropped.
            self._broker = Broker(xsub_endpoint=xsub, xpub_endpoint=xpub)
            self._broker.start()
            self.bus = make_bus_for_node(
                xsub_endpoint=xsub, xpub_endpoint=xpub)
            # Advertise where the bus is, on THIS machine only. A
            # subprocess node learns the endpoints from its parent via
            # env vars; anything we did not spawn — a monitor, a
            # recorder, a second terminal — had no way to find them.
            from jaeger_os.transport import rendezvous
            rendezvous.publish(self.spec.name, xsub=xsub, xpub=xpub)
        else:
            raise ValueError(
                f"bus backend {backend!r} not implemented in format 0.1 "
                f"(inproc | zmq)")
        # 0.8 U3: inject this chassis's bus into the brain-side runtime
        # singleton (jaeger_os.nodes.runtime) so ``ensure_tts_node`` /
        # ``ensure_animation_node`` / ``ensure_audio_session_node`` — and
        # the AgentCore's AgentBridge, which reads ``self.bus`` — all
        # share the ONE bus instead of two disconnected InProcBus
        # instances (the pre-U3 windowed-app duality). Lazy import: the
        # chassis stays importable without pulling in TTS/animation deps.
        from jaeger_os.nodes import runtime as node_runtime
        node_runtime.set_bus(self.bus)

    def _start_control(self) -> None:
        """Expose this app to outside tooling. Fail-soft: an app that
        cannot bind its control socket (a stale file, a second instance)
        must still run — losing introspection is not worth losing the
        app."""
        if not getattr(self.spec, "control", True):
            return
        try:
            from jaeger_os.app.control import ControlServer
            self._control = ControlServer(
                app_name=self.spec.name, supervisor=self.supervisor,
                catalog=self.catalog, health=self.health, bus=self.bus,
            ).start()
            log(self.spec.name, f"control: {self._control.endpoint}",
                bus=self.bus)
        except Exception as exc:  # noqa: BLE001
            self._control = None
            log(self.spec.name,
                f"control plane unavailable: {type(exc).__name__}: {exc}",
                level="warn", bus=self.bus)

    def _init_core(self) -> None:
        """Boot the Tier-1 core (manifest ``[core]``) on the MAIN thread,
        after the bus and BEFORE nodes/surfaces. Identity-critical: NOT
        supervised, no restart. Skipped when no ``[core]`` is declared.
        ``Core.__init__`` asserts the main thread."""
        core_spec = self.spec.core
        if not core_spec.enabled or not core_spec.factory:
            return
        from jaeger_os.core.modules import set_application_package
        set_application_package(core_spec.factory)
        cfg = slice_for(self.config, core_spec.config_key)
        fn = resolve_ref(core_spec.factory)
        self.core = fn(self.bus, {**core_spec.args, **cfg})
        self.core.setup()

    def _start_nodes(self) -> None:
        self.supervisor = Supervisor(health=self.health, bus=self.bus)
        # M2a: resolve any slot-bound nodes' factories before building
        # handles. One discover_modules() scan for the whole pass (it
        # walks jaeger_os/nodes/ on disk) rather than one per node.
        modules_by_slot = None
        if any(n.slot and not n.factory for n in self.spec.nodes):
            from jaeger_os.core.modules import discover_modules
            modules_by_slot = discover_modules(project_dir=self.root)
        for node_spec in self.spec.nodes:
            if node_spec.slot and not node_spec.factory:
                self._resolve_slot(node_spec, modules_by_slot)
                if not node_spec.factory:
                    # An optional slot nothing filled. _resolve_slot
                    # logged it and disabled the node; building a
                    # handle from an empty factory ref would raise.
                    continue
            self.supervisor.add(
                self._make_handle(node_spec, modules_by_slot))
        self.supervisor.start_all()
        # 0.8 U3b: register AFTER start_all() so jaeger_os.nodes.runtime's
        # ensure_tts_node/ensure_audio_session_node/ensure_animation_node —
        # called by the agent's speak/listen/avatar tools — delegate to
        # THIS supervisor for any node the manifest declares + enables,
        # instead of spawning a second thread per node (the pre-U3b
        # windowed-app double-spawn this manifest's [[node]] entries used
        # to guard against by staying disabled).
        from jaeger_os.nodes import runtime as node_runtime
        node_runtime.set_supervisor(self.supervisor)

    def _make_handle(self, node_spec: NodeSpec, modules_by_slot=None):
        cfg = slice_for(self.config, node_spec.config_key)
        if node_spec.backend == "thread":
            if node_spec.slot and not node_spec.factory:
                self._resolve_slot(node_spec, modules_by_slot)
            factory_fn = resolve_ref(node_spec.factory)

            def factory(fn=factory_fn, spec=node_spec, cfg=cfg):
                return fn(self.bus, {**spec.args, **cfg})

            return ThreadHandle(node_spec, factory)
        if node_spec.backend == "subprocess":
            import json as _json
            env_extra = dict(self._broker.env()) if self._broker else {}
            env_extra["JAEGER_NODE_CONFIG"] = _json.dumps(
                {**node_spec.args, **cfg})
            return SubprocessHandle(
                node_spec, env_extra=env_extra, cwd=self.root,
                registry_file=self._registry_file,
            )
        raise ValueError(
            f"node {node_spec.id!r}: backend {node_spec.backend!r} "
            "not implemented in format 0.1 (thread | subprocess)"
        )

    def _resolve_slot(self, node_spec: NodeSpec, modules_by_slot=None) -> None:
        """M2a: populate ``node_spec.factory`` from ``discover_modules()``
        for a ``slot=``-bound node. Fail-closed — a declared node with no
        module backing its slot is a manifest bug, not a silent skip.
        Zero modules for the slot raises naming the slot; more than one
        picks deterministically (sorted by module name) and logs the
        choice — real multi-engine selection is a later config concern."""
        if modules_by_slot is None:
            from jaeger_os.core.modules import discover_modules
            modules_by_slot = discover_modules(project_dir=self.root)
        candidates = modules_by_slot.get(node_spec.slot, [])
        if not candidates:
            if node_spec.optional:
                # Declared, absent, and that is allowed. Logged rather
                # than silent: an operator who installed a voice and
                # does not hear one needs to know the app looked and
                # found nothing.
                log("app", f"node {node_spec.id!r}: no module provides "
                           f"slot {node_spec.slot!r} — skipped (optional)",
                    level="warn", bus=self.bus)
                node_spec.enabled = False
                return
            raise ValueError(
                f"node {node_spec.id!r}: no module provides "
                f"slot {node_spec.slot!r}"
            )
        chosen = sorted(candidates, key=lambda m: m.module)[0]
        if len(candidates) > 1:
            log(self.spec.name,
                f"node {node_spec.id!r}: slot {node_spec.slot!r} has "
                f"{len(candidates)} modules "
                f"({sorted(m.module for m in candidates)}); "
                f"chose {chosen.module!r}", bus=self.bus)
        node_spec.factory = chosen.factory

    def _install_signals(self) -> None:
        def handler(signum: int, frame: Any) -> None:  # noqa: ARG001
            log(self.spec.name, f"signal {signum}; shutting down")
            if self._qt_app is not None:
                self._qt_app.quit()
            else:
                self.shutdown()
                sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, handler)
            signal.signal(signal.SIGINT, handler)
        except (ValueError, OSError):
            pass   # not on the main thread (tests)

    def _run_qt(self) -> int:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        qt_app = QApplication.instance() or QApplication(sys.argv)
        qt_app.setQuitOnLastWindowClosed(self.spec.shell_quits_core)
        self._qt_app = qt_app
        main_obj = self.surfaces.start_all(
            self.spec.surfaces, resolve_ref, self)
        if main_obj is not None and hasattr(main_obj, "show"):
            main_obj.show()
        # Pump so Ctrl-C in the terminal reaches the Python handler.
        pump = QTimer()
        pump.timeout.connect(lambda: None)
        pump.start(200)
        return qt_app.exec()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


__all__ = ["JaegerApp", "SecondInstanceError", "resolve_ref"]
