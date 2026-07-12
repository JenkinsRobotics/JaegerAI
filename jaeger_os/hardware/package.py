"""HardwarePackage — topology.yaml → validated robot description.

A package directory (``jaeger_os/hardware/packages/<robot>/``) holds
``topology.yaml`` plus ``adapters/``, ``devices/``, ``capabilities.py``.
The loader validates STRICTLY (unknown fields refuse, missing adapters
refuse, framework-version mismatch refuses) — loudly at load time with
the offending entry named, never a silent degrade. The schema ships
with its validator in the same commit (standing rule).

The schema TYPES (``PackageSpec`` and friends) live in
``jaeger_os.contract.capability`` (0.9 contract package) — re-exported here
unchanged so existing ``from .package import PackageSpec`` call sites keep
working. This module owns the LOADER: parsing, validation, ref resolution,
and transport/link construction.
"""

from __future__ import annotations

import importlib
import pathlib
from typing import Any

import msgspec

from jaeger_os.contract.capability import (
    CapabilitySpec,
    ControllerSpec,
    LinkSpec,
    PackageSpec,
    RelaySpec,
    SafetySpec,
)

from . import link as _link_mod
from .protocol import make_protocol
from .transport import MockTransport, SerialTransport, Transport, ZmqReqTransport


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.strip().lstrip(">=").split(".") if p.isdigit())


def _check_framework_version(requirement: str) -> None:
    from . import FRAMEWORK_VERSION
    req = requirement.strip()
    if not req:
        return
    if not req.startswith(">="):
        raise ValueError(
            f"requires_framework supports only '>=X.Y' constraints, got {req!r}"
        )
    if _version_tuple(req) > _version_tuple(FRAMEWORK_VERSION):
        raise RuntimeError(
            f"package needs framework {req}, this is {FRAMEWORK_VERSION} — "
            "refusing to load (upgrade JROS or relax the constraint)"
        )


def load_package(path: str | pathlib.Path) -> PackageSpec:
    """Parse + validate ``<path>/topology.yaml``.

    ``path`` may be the package directory or the yaml file itself.
    Raises with the offending field named on any schema violation."""
    import yaml

    p = pathlib.Path(path)
    if p.is_dir():
        p = p / "topology.yaml"
    if not p.is_file():
        raise FileNotFoundError(f"no topology at {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    try:
        spec = msgspec.convert(raw, PackageSpec)
    except msgspec.ValidationError as exc:
        raise ValueError(f"{p}: {exc}") from None
    _check_framework_version(spec.requires_framework)
    # Capability names must be subsystem.action and reference a
    # declared controller (or "*").
    for cap in spec.capabilities:
        if "." not in cap.name.strip("."):
            raise ValueError(
                f"{p}: capability {cap.name!r} must be 'subsystem.action'"
            )
        if cap.controller != "*" and cap.controller not in spec.controllers:
            raise ValueError(
                f"{p}: capability {cap.name!r} references unknown "
                f"controller {cap.controller!r}"
            )
    if spec.safety:
        for node_id in spec.safety.estop_scope:
            if node_id not in spec.controllers:
                raise ValueError(
                    f"{p}: safety.estop_scope names unknown controller "
                    f"{node_id!r}"
                )
    return spec


def resolve_ref(ref: str, *, package: str) -> Any:
    """Resolve ``"jp01.adapters.mc01:Mc01MotorAdapter"`` →  the object.
    Package-relative refs (leading package name) resolve inside
    ``jaeger_os.hardware.packages``; fully-dotted refs pass through."""
    mod_path, _, attr = ref.partition(":")
    if not attr:
        raise ValueError(f"ref {ref!r} must be 'module:attr'")
    if mod_path.split(".", 1)[0] == package:
        mod_path = f"jaeger_os.hardware.packages.{mod_path}"
    module = importlib.import_module(mod_path)
    try:
        return getattr(module, attr)
    except AttributeError:
        raise ImportError(f"{mod_path} has no attribute {attr!r}") from None


def build_transport(link: LinkSpec, *, simulated: bool,
                    mock_responder: Any = None) -> Transport:
    """LinkSpec → primary Transport (relay built separately).
    ``simulated: true`` overrides everything with a MockTransport."""
    if simulated or link.transport == "mock":
        return MockTransport(responder=mock_responder, name=link.port or "sim")
    if link.transport == "serial":
        if not link.port:
            raise ValueError("serial link needs a 'port'")
        return SerialTransport(port=link.port, baud=link.baud)
    if link.transport == "zmq_req":
        if not link.endpoint:
            raise ValueError("zmq_req link needs an 'endpoint'")
        return ZmqReqTransport(endpoint=link.endpoint, target=link.target)
    raise ValueError(f"unknown transport {link.transport!r}")


def build_link(
    name: str,
    controller: ControllerSpec,
    *,
    on_event: Any = None,
    mock_responder: Any = None,
) -> "_link_mod.Link":
    """ControllerSpec → ready-to-open Link (primary + optional relay).
    Simulated controllers never build a relay — the mock IS the wire."""
    primary = build_transport(
        controller.link, simulated=controller.simulated,
        mock_responder=mock_responder,
    )
    relay: Transport | None = None
    if controller.link.relay is not None and not controller.simulated:
        r = controller.link.relay
        if r.transport != "zmq_req":
            raise ValueError(
                f"{name}: relay transport must be zmq_req, got {r.transport!r}"
            )
        relay = ZmqReqTransport(endpoint=r.endpoint, target=r.target)
    return _link_mod.Link(
        transport=primary,
        protocol=make_protocol(controller.link.protocol),
        relay=relay,
        on_event=on_event,
        name=name,
    )


__all__ = [
    "PackageSpec", "ControllerSpec", "CapabilitySpec", "LinkSpec",
    "RelaySpec", "SafetySpec",
    "load_package", "resolve_ref", "build_transport", "build_link",
]
