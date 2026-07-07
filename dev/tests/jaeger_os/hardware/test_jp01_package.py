"""JP01 package — simulated end-to-end tests (plan §4.2 step 2).

Boots the real package (real topology.yaml, real adapters, firmware-
shaped mock responders) on an InProcBus and exercises both command
paths: capability tools → adapter → wire, and bus topics → generic
nodes → adapter → wire. No hardware, no serial, no ZMQ.
"""

from __future__ import annotations

import time

import pytest

from jaeger_os.transport import topics
from jaeger_os.agent.schemas.tool_registry import get_tool, has_tool
from jaeger_os.core.safety.permissions import (
    AllowAllProvider,
    DenyAllProvider,
    PermissionPolicy,
    use_policy,
)
from jaeger_os.hardware.packages.jp01 import boot as jp01_boot
from jaeger_os.transport import InProcBus


def _wire(rt, controller):
    """The MockTransport behind a simulated controller's link."""
    return rt.links[controller]._active


@pytest.fixture
def jp01(monkeypatch):
    monkeypatch.setenv("JAEGER_DEV_MODE", "1")
    bus = InProcBus()
    rt = jp01_boot.load(bus=bus)
    policy = PermissionPolicy(confirmation=AllowAllProvider())
    with use_policy(policy):
        yield rt, bus
    jp01_boot.shutdown()
    bus.close()


def test_boot_is_fully_simulated_and_idempotent(jp01):
    rt, bus = jp01
    assert all(c.simulated for c in rt.spec.controllers.values())
    assert all(link.connected for link in rt.links.values())
    assert jp01_boot.load(bus=bus) is rt          # second load = same runtime
    # Handshake went out exactly once per serial controller.
    assert _wire(rt, "mc01").writes.count(b"CN\n") == 1
    assert _wire(rt, "avc01").writes.count(b"CN\n") == 1


def test_umbrella_tools_registered_beta_gated(jp01):
    for name in ("motion", "lights", "robot_vision", "telemetry"):
        assert has_tool(name)
        assert get_tool(name).beta is True
    assert get_tool("motion").dangerous is True
    assert get_tool("motion").side_effect == "hardware"
    assert get_tool("telemetry").side_effect == "read"


def test_move_joints_hits_the_wire_with_firmware_clamps(jp01):
    rt, _ = jp01
    result = get_tool("motion").fn(action="move_joints", a1=90, a2=100)
    assert result["ok"] is True and result["sent"] == "MJ[90,100,10]"
    assert _wire(rt, "mc01").writes[-1] == b"MJ[90,100,10]\n"
    # Out of firmware range → refused at the tool boundary, not bent.
    bad = get_tool("motion").fn(action="move_joints", a1=10, a2=100)
    assert bad["ok"] is False and "invalid arguments" in bad["error"]


def test_drive_respects_two_second_firmware_cap(jp01):
    rt, _ = jp01
    ok = get_tool("motion").fn(action="drive", s1=50, s2=-50, duration_s=1.5)
    assert ok["ok"] is True
    assert _wire(rt, "mc01").writes[-1] == b"MM[50,-50,2]\n"
    too_long = get_tool("motion").fn(action="drive", s1=10, s2=10,
                                     duration_s=9.0)
    assert too_long["ok"] is False


def test_stop_latches_and_only_operator_releases(jp01):
    rt, _ = jp01
    result = get_tool("motion").fn(action="stop")
    assert result["ok"] is True and result["estop_latched"] is True
    assert _wire(rt, "mc01").writes[-1] == b"MM[0,0,0]\n"
    # HARDWARE motion refuses while latched…
    refused = get_tool("motion").fn(action="move_joints", a1=90, a2=100)
    assert refused["ok"] is False and "e-stop latched" in refused["error"]
    # …stop itself stays callable (re-stop during latch)…
    again = get_tool("motion").fn(action="stop")
    assert again["ok"] is True
    assert _wire(rt, "mc01").writes[-1] == b"MM[0,0,0]\n"
    # …lights and telemetry keep working…
    assert get_tool("lights").fn(action="set_mode", target="matrix",
                                 mode=2)["ok"] is True
    assert get_tool("telemetry").fn(action="read")["ok"] is True
    # …and release is the operator's.
    rt.estop.release(source="operator")
    moved = get_tool("motion").fn(action="move_joints", a1=90, a2=100)
    assert moved["ok"] is True


def test_lights_actions_use_device_builders(jp01):
    rt, _ = jp01
    get_tool("lights").fn(action="set_mode", target="neopixel", mode=3)
    assert _wire(rt, "avc01").writes[-1] == b"MN[3]\n"
    get_tool("lights").fn(action="set_frame", target="matrix",
                          frame_hex="ff0000" * 2)
    assert _wire(rt, "avc01").writes[-1] == b"FM[ff0000ff0000]\n"
    get_tool("lights").fn(action="brightness", value=128)
    assert _wire(rt, "avc01").writes[-1] == b"BM[128]\n"
    bad = get_tool("lights").fn(action="set_frame", target="matrix",
                                frame_hex="not-hex!")
    assert bad["ok"] is False


def test_bus_motion_path_through_motor_node(jp01):
    rt, bus = jp01
    bus.publish(topics.MotionCommand(linear_x_mps=0.25, duration_s=1.0))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _wire(rt, "mc01").writes[-1] == b"MM[50,50,1]\n":
            break
        time.sleep(0.01)
    assert _wire(rt, "mc01").writes[-1] == b"MM[50,50,1]\n"


def test_bus_light_path_through_light_node(jp01):
    rt, bus = jp01
    bus.publish(topics.LightCommand(rgb=[255, 0, 0], pattern="solid"))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if _wire(rt, "avc01").writes[-1] == b"FN[00ff0000]\n":
            break
        time.sleep(0.01)
    assert _wire(rt, "avc01").writes[-1] == b"FN[00ff0000]\n"


def test_node_health_heartbeats_publish(jp01):
    """jp01's own per-controller heartbeat (``_start_health_heartbeat``,
    kept — not retired — by 0.8 U3; see its docstring) covers every
    controller, including vcc01 which has no dedicated node at all, and
    carries real ``link_connected``. 0.8 U3 ALSO made every
    ``nodes.base.Node`` heartbeat generically (mc01/avc01's MotorNode/
    LightNode now additionally publish as ``jp01-motor``/``jp01-light``
    with no hardware knowledge — ``link_connected=False`` there is
    correct, not a bug), so the link-state assertion below is scoped to
    jp01's own per-controller messages, not every message on the topic."""
    rt, bus = jp01
    seen: list = []
    bus.subscribe(topics.SENSE_NODE_HEALTH, seen.append)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if {m.node for m in seen} >= {"jp01-mc01", "jp01-avc01",
                                      "jp01-vcc01"}:
            break
        time.sleep(0.05)
    nodes = {m.node for m in seen}
    assert {"jp01-mc01", "jp01-avc01", "jp01-vcc01"} <= nodes
    controller_beats = [m for m in seen
                        if m.node in {"jp01-mc01", "jp01-avc01", "jp01-vcc01"}]
    assert all(m.link_connected for m in controller_beats)


def test_telemetry_read_carries_heartbeats_and_estop(jp01):
    rt, _ = jp01
    _wire(rt, "mc01").inject(b"--- STATUS UPDATE --- sim beat\n")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if rt.adapters["mc01"].telemetry()["last_heartbeat"]:
            break
        time.sleep(0.01)
    snapshot = get_tool("telemetry").fn(action="read")
    assert snapshot["ok"] is True
    assert "STATUS UPDATE" in snapshot["controllers"]["mc01"]["last_heartbeat"]
    assert snapshot["controllers"]["estop"]["engaged"] is False


def test_robot_vision_stream_info_reports_topology(jp01):
    info = get_tool("robot_vision").fn(action="stream_info")
    assert info["ok"] is True
    assert info["streams"]["telemetry"] == "tcp://192.168.2.2:5555"
    assert info["streams"]["video_udp"] == [5001, 5003]


def test_motion_denied_without_confirmation_provider(jp01):
    with use_policy(PermissionPolicy(confirmation=DenyAllProvider())):
        result = get_tool("motion").fn(action="move_joints", a1=90, a2=100)
    assert result["ok"] is False
    assert "confirmation refused" in result["error"]


def test_shutdown_neutralizes_and_blanks(monkeypatch):
    monkeypatch.setenv("JAEGER_DEV_MODE", "1")
    bus = InProcBus()
    rt = jp01_boot.load(bus=bus)
    mc01_wire = _wire(rt, "mc01")
    avc01_wire = _wire(rt, "avc01")
    jp01_boot.shutdown()
    bus.close()
    assert b"MM[0,0,0]\n" in mc01_wire.writes      # motors neutralized
    assert b"MN[0]\n" in avc01_wire.writes          # neopixel blanked
    assert b"MM[0]\n" in avc01_wire.writes          # matrix blanked
    assert not any(link.connected for link in rt.links.values())
    assert not has_tool("motion")                   # tools unregistered
    assert jp01_boot.get_runtime() is None
