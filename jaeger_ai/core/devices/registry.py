"""Generic Device and Node Registry (Workstream 13).

Manages device registration, pairing secrets, capability negotiation,
connection states, heartbeats, and stale-device detection.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Literal
import uuid

from jaeger_ai.contract.schemas import Device
from .models import DeviceCapability, DevicePairingSecret, DeviceTelemetry, DeviceType

logger = logging.getLogger("jaeger.core.devices.registry")


class DeviceError(RuntimeError):
    pass


class DeviceRegistry:
    """Canonical registry managing connected clients, devices, and nodes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, Device] = {}
        self._secrets: dict[str, str] = {}  # device_id -> hashed_secret
        self._revoked: set[str] = set()

    def pair_device(
        self,
        name: str,
        device_type: DeviceType | str,
        owner_entity: str = "agent:jaeger",
        *,
        capabilities: list[str] | None = None,
        permissions: list[str] | None = None,
        transport: Literal["websocket", "sse", "unix_socket", "rest"] = "sse",
        device_id: str | None = None,
    ) -> tuple[Device, str]:
        """Register and pair a new client or device node, returning device and pairing secret."""
        did = device_id or f"dev_{uuid.uuid4().hex[:12]}"
        d_type = device_type.value if isinstance(device_type, DeviceType) else str(device_type)
        raw_secret = secrets.token_urlsafe(32)
        hashed = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()

        device = Device(
            device_id=did,
            owner_entity=owner_entity,
            name=name.strip(),
            device_type=d_type,
            connection_state="connected",
            transport=transport,
            capabilities=list(capabilities or []),
            permissions=list(permissions or []),
            last_seen=time.time(),
        )

        with self._lock:
            self._devices[did] = device
            self._secrets[did] = hashed
            self._revoked.discard(did)
            logger.info("Paired device %s (%s, %s) owned by %s", did, name, d_type, owner_entity)
            return device, raw_secret

    def authenticate_device(self, device_id: str, secret_token: str) -> bool:
        """Authenticate a device token against stored pairing secret."""
        with self._lock:
            if device_id in self._revoked:
                return False
            stored_hash = self._secrets.get(device_id)
            if not stored_hash:
                return False

            candidate_hash = hashlib.sha256(secret_token.encode("utf-8")).hexdigest()
            valid = hmac.compare_digest(stored_hash, candidate_hash)
            if valid:
                dev = self._devices.get(device_id)
                if dev:
                    object.__setattr__(dev, "last_seen", time.time())
                    object.__setattr__(dev, "connection_state", "connected")
            return valid

    def revoke_device(self, device_id: str) -> bool:
        """Revoke a device's pairing authorization."""
        with self._lock:
            if device_id not in self._devices:
                return False
            self._revoked.add(device_id)
            dev = self._devices[device_id]
            object.__setattr__(dev, "connection_state", "disconnected")
            logger.info("Revoked device pairing for %s (%s)", device_id, dev.name)
            return True

    def heartbeat(
        self,
        device_id: str,
        telemetry: dict[str, Any] | None = None,
    ) -> Device:
        """Record live heartbeat and telemetry from a device."""
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                raise DeviceError(f"Device {device_id} not registered")
            if device_id in self._revoked:
                raise DeviceError(f"Device {device_id} has been revoked")

            now = time.time()
            object.__setattr__(dev, "last_seen", now)
            object.__setattr__(dev, "connection_state", "connected")
            if telemetry:
                merged_health = dict(dev.health)
                merged_health.update(telemetry)
                object.__setattr__(dev, "health", merged_health)
            return dev

    def disconnect(self, device_id: str) -> Device:
        """Mark device as disconnected."""
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                raise DeviceError(f"Device {device_id} not registered")
            object.__setattr__(dev, "connection_state", "disconnected")
            return dev

    def reconnect(self, device_id: str) -> Device:
        """Reconnect a previously disconnected device."""
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                raise DeviceError(f"Device {device_id} not registered")
            if device_id in self._revoked:
                raise DeviceError(f"Device {device_id} is revoked")
            object.__setattr__(dev, "connection_state", "connected")
            object.__setattr__(dev, "last_seen", time.time())
            return dev

    def negotiate_capabilities(
        self,
        device_id: str,
        requested_capabilities: list[str],
    ) -> list[str]:
        """Negotiate and return intersection of requested vs supported device capabilities."""
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                raise DeviceError(f"Device {device_id} not registered")

            supported = set(dev.capabilities)
            negotiated = [cap for cap in requested_capabilities if cap in supported]
            return negotiated

    def detect_stale_devices(self, timeout_seconds: float = 60.0) -> list[Device]:
        """Scan and flag connected devices whose heartbeat has exceeded timeout as stale."""
        now = time.time()
        stale_list = []
        with self._lock:
            for dev in self._devices.values():
                if dev.connection_state == "connected" and (now - dev.last_seen) > timeout_seconds:
                    object.__setattr__(dev, "connection_state", "stale")
                    stale_list.append(dev)
                    logger.warning("Device %s marked stale (last seen %.1fs ago)", dev.device_id, now - dev.last_seen)
        return stale_list

    def get_device(self, device_id: str) -> Device | None:
        with self._lock:
            return self._devices.get(device_id)

    def list_devices(
        self,
        *,
        owner_entity: str | None = None,
        connection_state: str | None = None,
    ) -> list[Device]:
        with self._lock:
            res = list(self._devices.values())
            if owner_entity:
                res = [d for d in res if d.owner_entity == owner_entity]
            if connection_state:
                res = [d for d in res if d.connection_state == connection_state]
            return res
