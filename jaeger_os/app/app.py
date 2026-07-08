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

from jaeger_os.transport import Bus, InProcBus

from .config import load_config, slice_for
from .core import Core
from .health import HealthCache
from .logging import log
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
        if self.spec.config:
            cfg_path = self.root / self.spec.config
            self.config = load_config(cfg_path) if cfg_path.exists() else {}
        else:
            self.config = {}
        self._build_bus()
        self.health = HealthCache(self.bus)
        self._init_core()
        self._start_nodes()
        self._install_signals()
        atexit.register(self.shutdown)
        log(self.spec.name,
            f"booted: {len([n for n in self.spec.nodes if n.enabled])} "
            f"nodes, bus={self.spec.bus.backend}, "
            f"mode={self.spec.mode}", bus=self.bus)
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

    def shutdown(self) -> None:
        """Reverse boot order. Idempotent; never raises; the
        windows-die-together + no-orphans moment."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
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
        self.bus = InProcBus()
        # 0.8 U3: inject this chassis's bus into the brain-side runtime
        # singleton (jaeger_os.nodes.runtime) so ``ensure_tts_node`` /
        # ``ensure_animation_node`` / ``ensure_audio_session_node`` — and
        # the AgentCore's AgentBridge, which reads ``self.bus`` — all
        # share the ONE bus instead of two disconnected InProcBus
        # instances (the pre-U3 windowed-app duality). Lazy import: the
        # chassis stays importable without pulling in TTS/animation deps.
        from jaeger_os.nodes import runtime as node_runtime
        node_runtime.set_bus(self.bus)

    def _init_core(self) -> None:
        """Boot the Tier-1 core (manifest ``[core]``) on the MAIN thread,
        after the bus and BEFORE nodes/surfaces. Identity-critical: NOT
        supervised, no restart. Skipped when no ``[core]`` is declared.
        ``Core.__init__`` asserts the main thread."""
        core_spec = self.spec.core
        if not core_spec.enabled or not core_spec.factory:
            return
        cfg = slice_for(self.config, core_spec.config_key)
        fn = resolve_ref(core_spec.factory)
        self.core = fn(self.bus, {**core_spec.args, **cfg})
        self.core.setup()

    def _start_nodes(self) -> None:
        self.supervisor = Supervisor(health=self.health, bus=self.bus)
        for node_spec in self.spec.nodes:
            self.supervisor.add(self._make_handle(node_spec))
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

    def _make_handle(self, node_spec: NodeSpec):
        cfg = slice_for(self.config, node_spec.config_key)
        if node_spec.backend == "thread":
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
