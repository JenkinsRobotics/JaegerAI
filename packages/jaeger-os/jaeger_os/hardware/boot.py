"""Generic hardware-package boot — config name → package runtime.

``config.yaml``'s ``hardware.package: jp01`` resolves to
``jaeger_os.hardware.packages.jp01.boot:load`` by convention. Every
package boot module exposes ``load(bus=None)`` and ``shutdown()``;
this wrapper keeps main.py free of per-robot imports.

J5A (2026-06-13) adds ``make_jp01_hardware`` — a chassis-contract
factory ``(bus, config) -> runtime`` the format 0.1 supervisor can
resolve from jaeger.toml's [[node]] entries. It wraps boot_hardware's
``package`` first-positional argument behind the chassis's
``(bus, config_dict)`` shape.
"""

from __future__ import annotations

import importlib
from typing import Any


def make_jp01_hardware(bus: Any, config: dict[str, Any]) -> Any:
    """Chassis-contract factory for the JP01 hardware package.

    The format 0.1 chassis Supervisor calls ``factory(bus, config)``
    where config is ``{**spec.args, **config_slice}``; jaeger.toml's
    JP01 node carries ``args = { package = "jp01" }``, so this
    wrapper just forwards.

    Returns whatever ``boot_hardware("jp01", bus=bus)`` returns
    (the JP01 PackageRuntime). When J5B wires the chassis supervisor
    onto JROS, the supervisor's ThreadHandle treats the returned
    object as the running node and drives its lifecycle.
    """
    package = str(config.get("package", "jp01"))
    return boot_hardware(package, bus=bus)


def boot_hardware(package: str, *, bus: Any = None) -> Any:
    """Load + boot the named package. Raises with the package named
    when the directory or its boot module is missing — a typo'd
    config refuses loudly instead of silently robot-less."""
    name = package.strip().lower()
    if not name.replace("_", "").isalnum():
        raise ValueError(f"invalid hardware package name {name!r}")
    try:
        mod = importlib.import_module(
            f"jaeger_os.hardware.packages.{name}.boot"
        )
    except ModuleNotFoundError as exc:
        raise ValueError(
            f"unknown hardware package {name!r} — expected "
            f"jaeger_os/hardware/packages/{name}/boot.py ({exc})"
        ) from None
    return mod.load(bus=bus)


def shutdown_hardware(package: str) -> None:
    """Tear the named package down. Missing/never-booted = no-op."""
    name = package.strip().lower()
    try:
        mod = importlib.import_module(
            f"jaeger_os.hardware.packages.{name}.boot"
        )
    except ModuleNotFoundError:
        return
    mod.shutdown()


__all__ = ["boot_hardware", "shutdown_hardware"]
