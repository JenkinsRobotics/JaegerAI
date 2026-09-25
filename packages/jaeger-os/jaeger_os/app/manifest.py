"""jaeger.toml — the app manifest: what this app IS MADE OF.

Structure lives here (nodes, surfaces, bus, event loop, instance
policy); behavior lives in config.yaml (§config). The manifest is not
runtime-overridable — a different shape is a different manifest
(``jaeger.sim.toml`` is the sanctioned simulation profile).

Validation refuses loudly with the offending field named: unknown
keys, bad enums, missing factories, more than one main surface, and a
``requires_framework`` newer than this chassis copy's stamp.
"""

from __future__ import annotations

import dataclasses
import pathlib
import tomllib
from typing import Any

_MODES = ("fused", "split")
_EVENT_LOOPS = ("qt", "asyncio", "tui", "none")
_UIS = ("pyside6", "swift", "tui", "none")
_BACKENDS = ("thread", "subprocess", "external")
_RESTARTS = ("never", "on_failure", "always")
_BUS_BACKENDS = ("inproc", "zmq")


@dataclasses.dataclass
class BusSpec:
    backend: str = "inproc"
    xsub: str = ""
    xpub: str = ""


@dataclasses.dataclass
class CoreSpec:
    """The Tier-1 core (a singleton, optional). Built on the main thread,
    after the bus and before nodes/surfaces. Not supervised, no restart."""
    factory: str = ""          # "pkg.mod:fn" returning a Core
    config_key: str = ""
    enabled: bool = True
    args: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class NodeSpec:
    id: str
    tier: int = 3
    backend: str = "thread"
    factory: str = ""          # thread: "pkg.mod:fn" returning Node(s)
    slot: str = ""             # thread: resolve factory via discover_modules()[slot]
    module: str = ""           # subprocess: spawn `python -m module`
    restart: str = "on_failure"
    config_key: str = ""
    enabled: bool = True
    #: A slot-bound node whose module may legitimately be absent.
    #: Missing = logged and skipped, instead of refusing to boot.
    #:
    #: The distinction is capability, not taste: Mochi without its
    #: animation module has nothing to show and should fail loudly,
    #: while Mochi without a voice is a character that does not speak
    #: — which is exactly v5.0. Fail-closed stays the DEFAULT so a
    #: typo'd slot name is still a boot error.
    optional: bool = False
    #: The package that WOULD fill this slot, if you want it. A HINT,
    #: never a binding — the slot still takes whichever installed
    #: module claims it, and naming a package here does not privilege
    #: that one.
    #:
    #: It exists so tooling can answer "how do I get a voice?" without
    #: a registry. An empty optional slot is otherwise a dead end: the
    #: app knows it wants a `tts` and has no way to say what provides
    #: one.
    package: str = ""
    args: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class SurfaceSpec:
    id: str
    main: bool = False
    factory: str = ""          # "pkg.mod:fn" returning a Surface
    enabled: bool = True


@dataclasses.dataclass
class AppSpec:
    name: str
    #: Globally stable reverse-domain-style identity. ``name`` remains the
    #: operator-facing/runtime name and may differ between launch variants.
    id: str = ""
    type: str = "application"
    version: str = "0.0.0"
    requires_framework: str = ""
    mode: str = "fused"
    event_loop: str = "none"
    ui: str = "none"
    single_instance: bool = True
    autostart: bool = False
    shell_quits_core: bool = True
    config: str = "config.yaml"
    #: Settings written INLINE as [config.<key>] tables. A small app is
    #: then one file: topology and knobs in the same place, in the same
    #: format, with real types. Mutually exclusive with a config file —
    #: see load_manifest.
    inline_config: dict[str, Any] = dataclasses.field(default_factory=dict)
    # The control plane: an ipc socket letting a CLI/GUI in ANOTHER
    # process inspect and command this app. On by default because a
    # node-based app you cannot inspect from outside is the thing Mochi
    # 3.0's host monitor existed to fix. The socket lives under the
    # user's runtime dir with owner-only permissions; set false for a
    # locked-down deployment.
    control: bool = True
    bus: BusSpec = dataclasses.field(default_factory=BusSpec)
    core: CoreSpec = dataclasses.field(default_factory=CoreSpec)
    nodes: list[NodeSpec] = dataclasses.field(default_factory=list)
    surfaces: list[SurfaceSpec] = dataclasses.field(default_factory=list)


def _refuse(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(f"jaeger.toml: {msg}")


def _check_keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = set(table) - allowed
    _refuse(not unknown, f"unknown keys in {where}: {sorted(unknown)}")


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.strip().lstrip(">=").split(".")
                 if p.isdigit())


def load_manifest(path: str | pathlib.Path) -> AppSpec:
    """Parse + validate ``jaeger.toml``. ``path`` may be the file or
    its directory."""
    from . import FRAMEWORK_FORMAT

    p = pathlib.Path(path)
    if p.is_dir():
        p = p / "jaeger.toml"
    if not p.is_file():
        raise FileNotFoundError(f"no manifest at {p}")
    raw = tomllib.loads(p.read_text(encoding="utf-8"))

    _check_keys(raw, {"app", "bus", "core", "node", "surface", "config"},
                "top level")
    app_raw = raw.get("app") or {}

    # Settings written inline as [config.<key>] tables, so a small app
    # is ONE file. Refused alongside a config file rather than merged:
    # "which file is my setting in" is a question nobody should have to
    # ask, and a silent precedence rule is how you debug the wrong copy.
    inline_config = raw.get("config") or {}
    if inline_config and not isinstance(inline_config, dict):
        raise ValueError(f"{p}: [config] must be a table of tables")
    if inline_config and (p.parent / str(app_raw.get("config",
                                                     "config.yaml"))).is_file():
        raise ValueError(
            f"{p}: settings are in BOTH [config.*] here and "
            f"{app_raw.get('config', 'config.yaml')}. Pick one — delete the "
            f"file, or set config = \"\" in [app] to use the inline tables.")
    _check_keys(app_raw, {
        "id", "name", "type", "version", "requires_framework", "mode", "event_loop",
        "ui", "single_instance", "autostart", "shell_quits_core", "config",
        "control",
    }, "[app]")
    _refuse(bool(app_raw.get("name")), "[app] name is required")

    spec = AppSpec(
        name=str(app_raw["name"]),
        id=str(app_raw.get("id", "")),
        type=str(app_raw.get("type", "application")),
        version=str(app_raw.get("version", "0.0.0")),
        requires_framework=str(app_raw.get("requires_framework", "")),
        mode=str(app_raw.get("mode", "fused")),
        event_loop=str(app_raw.get("event_loop", "none")),
        ui=str(app_raw.get("ui", "none")),
        single_instance=bool(app_raw.get("single_instance", True)),
        autostart=bool(app_raw.get("autostart", False)),
        shell_quits_core=bool(app_raw.get("shell_quits_core", True)),
        config=str(app_raw.get("config", "config.yaml")),
        inline_config=inline_config,
        control=bool(app_raw.get("control", True)),
    )
    _refuse(spec.type == "application",
            f"[app] type {spec.type!r} must be 'application'")
    _refuse(spec.mode in _MODES, f"[app] mode {spec.mode!r} not in {_MODES}")
    _refuse(spec.event_loop in _EVENT_LOOPS,
            f"[app] event_loop {spec.event_loop!r} not in {_EVENT_LOOPS}")
    _refuse(spec.ui in _UIS, f"[app] ui {spec.ui!r} not in {_UIS}")

    req = spec.requires_framework.strip()
    if req:
        _refuse(req.startswith(">="),
                f"requires_framework supports only '>=X.Y', got {req!r}")
        if _version_tuple(req) > _version_tuple(FRAMEWORK_FORMAT):
            raise RuntimeError(
                f"app needs format {req}, this chassis copy is "
                f"{FRAMEWORK_FORMAT} — refusing to boot"
            )

    bus_raw = raw.get("bus") or {}
    _check_keys(bus_raw, {"backend", "xsub", "xpub"}, "[bus]")
    spec.bus = BusSpec(
        backend=str(bus_raw.get("backend", "inproc")),
        xsub=str(bus_raw.get("xsub", "")),
        xpub=str(bus_raw.get("xpub", "")),
    )
    _refuse(spec.bus.backend in _BUS_BACKENDS,
            f"[bus] backend {spec.bus.backend!r} not in {_BUS_BACKENDS}")

    if "core" in raw:
        core_raw = raw.get("core") or {}
        _check_keys(core_raw, {"factory", "config_key", "enabled", "args"},
                    "[core]")
        spec.core = CoreSpec(
            factory=str(core_raw.get("factory", "")),
            config_key=str(core_raw.get("config_key", "")),
            enabled=bool(core_raw.get("enabled", True)),
            args=dict(core_raw.get("args") or {}),
        )
        if spec.core.enabled:
            _refuse(bool(spec.core.factory),
                    "[core] an enabled core needs `factory`")

    for n_raw in raw.get("node") or []:
        _check_keys(n_raw, {
            "id", "tier", "backend", "factory", "slot", "module", "restart",
            "config_key", "enabled", "optional", "package", "args",
        }, "[[node]]")
        node = NodeSpec(
            id=str(n_raw.get("id", "")),
            tier=int(n_raw.get("tier", 3)),
            backend=str(n_raw.get("backend", "thread")),
            factory=str(n_raw.get("factory", "")),
            slot=str(n_raw.get("slot", "")),
            module=str(n_raw.get("module", "")),
            restart=str(n_raw.get("restart", "on_failure")),
            config_key=str(n_raw.get("config_key", "")),
            enabled=bool(n_raw.get("enabled", True)),
            optional=bool(n_raw.get("optional", False)),
            package=str(n_raw.get("package", "")),
            args=dict(n_raw.get("args") or {}),
        )
        _refuse(bool(node.id), "[[node]] id is required")
        _refuse(node.backend in _BACKENDS,
                f"node {node.id!r}: backend {node.backend!r} not in {_BACKENDS}")
        _refuse(node.restart in _RESTARTS,
                f"node {node.id!r}: restart {node.restart!r} not in {_RESTARTS}")
        if node.backend == "thread":
            _refuse(bool(node.factory or node.slot),
                    f"node {node.id!r}: thread backend needs "
                    "`factory` or `slot`")
        if node.backend == "subprocess":
            _refuse(bool(node.module),
                    f"node {node.id!r}: subprocess backend needs `module`")
        spec.nodes.append(node)
    ids = [n.id for n in spec.nodes]
    _refuse(len(ids) == len(set(ids)), f"duplicate node ids: {ids}")

    for s_raw in raw.get("surface") or []:
        _check_keys(s_raw, {"id", "main", "factory", "enabled"},
                    "[[surface]]")
        surface = SurfaceSpec(
            id=str(s_raw.get("id", "")),
            main=bool(s_raw.get("main", False)),
            factory=str(s_raw.get("factory", "")),
            enabled=bool(s_raw.get("enabled", True)),
        )
        _refuse(bool(surface.id), "[[surface]] id is required")
        _refuse(bool(surface.factory),
                f"surface {surface.id!r}: `factory` is required")
        spec.surfaces.append(surface)
    mains = [s for s in spec.surfaces if s.main and s.enabled]
    _refuse(len(mains) <= 1,
            f"at most one main surface; got {[s.id for s in mains]}")
    if spec.event_loop == "qt":
        _refuse(len(mains) == 1,
                "event_loop='qt' requires exactly one main surface")

    # Subprocess nodes can't ride the in-process bus.
    if any(n.backend == "subprocess" and n.enabled for n in spec.nodes):
        _refuse(spec.bus.backend == "zmq",
                "subprocess nodes require [bus] backend='zmq'")
    return spec


__all__ = ["AppSpec", "BusSpec", "CoreSpec", "NodeSpec", "SurfaceSpec",
           "load_manifest"]
