"""Product/Gateway composition root — owns mutable ModuleRegistry wiring.

Relocated out of ``jaeger-contracts`` so the contract spine stays pure and
stateless while the product/Gateway composition root owns runtime slot
registration and swapping.
"""

from __future__ import annotations

from typing import Any

from jaeger_contracts.ports import PORT_PROTOCOLS


class ModuleRegistry:
    """Stores and swaps implementations across JaegerAI's canonical module slots."""

    def __init__(self) -> None:
        self._slots: dict[str, dict[str, Any]] = {slot: {} for slot in PORT_PROTOCOLS}
        self._active: dict[str, str] = {}

    def register(
        self,
        slot: str,
        impl_id: str,
        instance: Any,
        *,
        activate: bool = False,
    ) -> None:
        proto = PORT_PROTOCOLS.get(slot)
        if proto is None:
            raise KeyError(f"Unknown module slot {slot!r}. Expected one of: {sorted(PORT_PROTOCOLS)}")
        if not isinstance(instance, proto):
            raise TypeError(
                f"Implementation {impl_id!r} for slot {slot!r} does not satisfy {proto.__name__}"
            )
        self._slots[slot][impl_id] = instance
        if activate or slot not in self._active:
            self._active[slot] = impl_id

    def use(self, slot: str, impl_id: str) -> Any:
        if slot not in self._slots or impl_id not in self._slots[slot]:
            raise KeyError(f"Implementation {impl_id!r} is not registered in slot {slot!r}")
        self._active[slot] = impl_id
        return self._slots[slot][impl_id]

    def get(self, slot: str, impl_id: str | None = None) -> Any:
        if slot not in self._slots:
            raise KeyError(f"Unknown module slot {slot!r}")
        target = impl_id or self._active.get(slot)
        if not target or target not in self._slots[slot]:
            raise KeyError(f"No active implementation for slot {slot!r}")
        return self._slots[slot][target]

    def active_id(self, slot: str) -> str | None:
        return self._active.get(slot)

    def list_slot(self, slot: str) -> list[str]:
        if slot not in self._slots:
            raise KeyError(f"Unknown module slot {slot!r}")
        return sorted(self._slots[slot].keys())

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            slot: {
                "active": self._active.get(slot),
                "registered": sorted(impls.keys()),
            }
            for slot, impls in self._slots.items()
        }


__all__ = ["ModuleRegistry"]
