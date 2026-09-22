"""Tests for Generic Device / Node Architecture (Workstream 13).

Verifies Invariants:
1. Phones, Macs, Web clients, Vision Pro, and future robots use the same generic contract.
2. Device pairing issues a secure token; token authenticates successfully.
3. Revocation blocks subsequent authentication and marks device disconnected.
4. Capability advertisement & negotiation filters supported features.
5. Reconnection lifecycle works cleanly.
6. Stale device detection catches missing heartbeats without crashing.
"""
import time
import pytest

from jaeger_ai.core.devices.models import DeviceCapability, DeviceType
from jaeger_ai.core.devices.registry import DeviceError, DeviceRegistry


@pytest.fixture
def registry():
    return DeviceRegistry()


def test_device_pairing_and_authentication(registry: DeviceRegistry):
    """Device pairs, receives secret, and authenticates successfully."""
    device, secret = registry.pair_device(
        name="Matthew's iPhone",
        device_type=DeviceType.PHONE,
        owner_entity="agent:jaeger",
        capabilities=[
            DeviceCapability.CAMERA.value,
            DeviceCapability.LOCATION.value,
            DeviceCapability.DISPLAY.value,
        ],
        transport="sse",
    )

    assert device.device_type == "phone"
    assert "camera" in device.capabilities
    assert device.connection_state == "connected"

    # Authenticate with valid secret
    assert registry.authenticate_device(device.device_id, secret) is True

    # Authenticate with bogus secret fails
    assert registry.authenticate_device(device.device_id, "invalid_secret_token") is False


def test_robot_embodiment_representation(registry: DeviceRegistry):
    """Future robotic embodiment is represented using the same canonical contract."""
    robot, secret = registry.pair_device(
        name="Unitree G1 Embodiment",
        device_type=DeviceType.ROBOT,
        owner_entity="agent:jaeger",
        capabilities=[
            DeviceCapability.MOTION.value,
            DeviceCapability.CAMERA.value,
            DeviceCapability.SENSORS.value,
            DeviceCapability.COMPUTE.value,
        ],
        transport="websocket",
    )

    assert robot.device_type == "robot"
    assert "motion" in robot.capabilities

    # Report live battery & sensor telemetry
    updated = registry.heartbeat(
        robot.device_id,
        telemetry={"battery_level": 0.88, "joint_temperatures": [42.1, 41.5]},
    )
    assert updated.health["battery_level"] == 0.88


def test_capability_negotiation(registry: DeviceRegistry):
    """Gateway and device negotiate the intersection of supported capabilities."""
    device, _ = registry.pair_device(
        name="Web Browser Client",
        device_type=DeviceType.WEB,
        capabilities=["display", "microphone"],
    )

    requested = ["display", "camera", "motion"]
    negotiated = registry.negotiate_capabilities(device.device_id, requested)

    # Only 'display' is supported by Web Browser Client
    assert negotiated == ["display"]


def test_revocation_lifecycle(registry: DeviceRegistry):
    """Revoking a device disables authentication and halts heartbeats."""
    device, secret = registry.pair_device(
        name="Compromised Tablet",
        device_type=DeviceType.PHONE,
    )

    assert registry.authenticate_device(device.device_id, secret) is True

    # Revoke
    revoked = registry.revoke_device(device.device_id)
    assert revoked is True
    assert device.connection_state == "disconnected"

    # Subsequent auth fails
    assert registry.authenticate_device(device.device_id, secret) is False

    # Subsequent heartbeat raises error
    with pytest.raises(DeviceError) as exc_info:
        registry.heartbeat(device.device_id)
    assert "revoked" in str(exc_info.value)


def test_disconnect_reconnect_and_stale_detection(registry: DeviceRegistry):
    """Lifecycle transitions between connected, disconnected, stale, and reconnected."""
    device, _ = registry.pair_device(
        name="Remote Sensor Node",
        device_type=DeviceType.SENSOR,
    )

    # 1. Manual disconnect
    d = registry.disconnect(device.device_id)
    assert d.connection_state == "disconnected"

    # 2. Reconnect
    r = registry.reconnect(device.device_id)
    assert r.connection_state == "connected"

    # 3. Simulate stale heartbeat timeout
    object.__setattr__(device, "last_seen", time.time() - 100.0)
    stale = registry.detect_stale_devices(timeout_seconds=30.0)
    assert len(stale) == 1
    assert stale[0].device_id == device.device_id
    assert device.connection_state == "stale"
