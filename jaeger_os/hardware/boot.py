"""Generic hardware-package boot — config name → package runtime.

``config.yaml``'s ``hardware.package: jp01`` resolves to
``jaeger_os.hardware.packages.jp01.boot:load`` by convention. Every
package boot module exposes ``load(bus=None)`` and ``shutdown()``;
this wrapper keeps main.py free of per-robot imports.
"""

from __future__ import annotations

import importlib
from typing import Any


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
