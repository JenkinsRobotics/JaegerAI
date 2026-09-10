"""Dependency-aware plane health checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen


@dataclass
class PlaneHealth:
    ok: bool
    bridge_ok: bool
    adapters: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "bridge_ok": self.bridge_ok,
            "adapters": dict(self.adapters),
            "details": dict(self.details),
            # Explicit honesty flag for dashboards / smoke.
            "honest": True,
            "rule": "adapter_up_requires_bridge_ok_for_plane_ok",
        }


def _http_ok(url: str, *, timeout_s: float = 2.0) -> bool:
    try:
        with urlopen(url, timeout=timeout_s) as resp:  # noqa: S310 — local health only
            status = int(getattr(resp, "status", 200) or 200)
            if status >= 400:
                return False
            body = resp.read(512)
    except (URLError, OSError, TimeoutError, ValueError):
        return False
    # Process-up only — callers must still require bridge_ok for plane honesty.
    if not body:
        return True
    lowered = body.lower()
    if b'"ok": false' in lowered or b'"ok":false' in lowered:
        return False
    return True


def check_plane_health(
    *,
    adapter_urls: dict[str, str] | None = None,
    bridge_health: Callable[[], dict[str, Any]] | None = None,
    require_bridge: bool = True,
) -> PlaneHealth:
    """Probe adapters + bridge; plane ``ok`` requires bridge when demanded.

    ``bridge_health`` should return a dict with truthy ``ok`` when the Jaeger
    bridge socket handshake succeeds (e.g. ``BridgeClient().health``).
    """
    adapters: dict[str, bool] = {}
    details: dict[str, Any] = {}

    for name, url in (adapter_urls or {}).items():
        adapters[name] = _http_ok(url)
        details[f"adapter:{name}"] = {"url": url, "up": adapters[name]}

    bridge_ok = True
    bridge_payload: dict[str, Any] | None = None
    if bridge_health is not None:
        try:
            bridge_payload = bridge_health()
            bridge_ok = bool(bridge_payload and bridge_payload.get("ok"))
        except Exception as exc:  # noqa: BLE001
            bridge_ok = False
            bridge_payload = {"ok": False, "error": str(exc)}
        details["bridge"] = bridge_payload

    if require_bridge:
        plane_ok = bridge_ok and (all(adapters.values()) if adapters else bridge_ok)
    else:
        plane_ok = all(adapters.values()) if adapters else bridge_ok

    # Honesty: if any adapter is up while bridge is down, surface split-brain.
    if adapters and any(adapters.values()) and not bridge_ok:
        details["split_brain"] = True
        plane_ok = False

    return PlaneHealth(ok=plane_ok, bridge_ok=bridge_ok, adapters=adapters, details=details)
