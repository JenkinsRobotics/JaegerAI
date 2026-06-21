"""Hardware framework — headless tests against MockTransport.

Covers the full plan §4.2 step-1 surface: protocol framing, transport
contracts, Link dual-path fallback + RX, topology loading/validation,
the e-stop latch, and capability→ToolDef registration including the
tier / e-stop / offline fail-closed paths.
"""

from __future__ import annotations

import sys
import time
import types

import pytest
from pydantic import BaseModel, Field

from jaeger_os import topics
from jaeger_os.agent.schemas.tool_registry import get_tool, has_tool, unregister_tool
from jaeger_os.core.safety.permissions import (
    AllowAllProvider,
    DenyAllProvider,
    PermissionPolicy,
    PermissionRequest,
    PermissionTier,
    PermissionDenied,
    use_policy,
)
from jaeger_os.hardware import (
    AsciiBracketProtocol,
    EStopLatch,
    JsonLineProtocol,
    Link,
    MockTransport,
    load_package,
    register_package_capabilities,
)
from jaeger_os.hardware.package import (
    LinkSpec,
    build_link,
    build_transport,
    resolve_ref,
)
from jaeger_os.hardware.protocol import make_protocol
from jaeger_os.transport import InProcBus


# ── protocol: ascii brackets ───────────────────────────────────────────


def test_bracket_encode_str_passthrough():
    p = AsciiBracketProtocol()
    assert p.encode("CN") == b"CN\n"
    assert p.encode("MJ[90,100,10]") == b"MJ[90,100,10]\n"


def test_bracket_encode_header_args():
    p = AsciiBracketProtocol()
    assert p.encode({"header": "MJ", "args": [90, 100, 10]}) == b"MJ[90,100,10]\n"
    assert p.encode({"header": "MM", "args": [0, 0, 0]}) == b"MM[0,0,0]\n"


def test_bracket_encode_header_payload_and_bare():
    p = AsciiBracketProtocol()
    assert p.encode({"header": "FN", "payload": "ffaa00" * 3}) == (
        b"FN[" + b"ffaa00" * 3 + b"]\n"
    )
    assert p.encode({"header": "GT"}) == b"GT\n"


def test_bracket_encode_refuses_garbage():
    p = AsciiBracketProtocol()
    with pytest.raises(ValueError):
        p.encode({"args": [1]})        # no header
    with pytest.raises(TypeError):
        p.encode(42)


def test_bracket_feed_buffers_partial_lines():
    p = AsciiBracketProtocol()
    assert p.feed(b"JP01-MC01 Con") == []
    events = p.feed(b"nected\nMJ done\n")
    assert [e.text for e in events] == ["JP01-MC01 Connected", "MJ done"]
    assert all(e.kind == "line" for e in events)


def test_bracket_feed_classifies_heartbeat_telemetry():
    p = AsciiBracketProtocol()
    events = p.feed(b"--- STATUS UPDATE ---\nok\n")
    assert events[0].kind == "telemetry"
    assert events[1].kind == "line"


def test_json_line_protocol_roundtrip():
    p = JsonLineProtocol()
    wire = p.encode({"target": "motion", "cmd": "MJ[90,100,10]"})
    assert wire.endswith(b"\n")
    events = p.feed(b'{"ok": true, "v": 3}\nnot-json\n')
    assert events[0].kind == "json" and events[0].data == {"ok": True, "v": 3}
    assert events[1].kind == "line" and events[1].text == "not-json"


def test_make_protocol_refuses_unknown():
    with pytest.raises(ValueError, match="unknown protocol"):
        make_protocol("morse")


# ── transport: mock contract ───────────────────────────────────────────


def test_mock_transport_lifecycle_and_responder():
    replies = {"CN": b"JP01-MC01 Connected\n"}
    mock = MockTransport(
        responder=lambda data: replies.get(data.decode().strip()),
    )
    with pytest.raises(ConnectionError):
        mock.write_bytes(b"CN\n")      # not open yet
    mock.open()
    mock.write_bytes(b"CN\n")
    assert mock.writes == [b"CN\n"]
    assert mock.read_bytes() == b"JP01-MC01 Connected\n"
    assert mock.read_bytes() is None
    mock.inject(b"--- STATUS UPDATE ---\n")
    assert mock.read_bytes() == b"--- STATUS UPDATE ---\n"
    mock.close()
    assert not mock.is_open()
    mock.close()                       # idempotent


# ── link: dual-path + RX ───────────────────────────────────────────────


class _FailingTransport(MockTransport):
    def open(self) -> None:
        raise ConnectionError("port gone")


def test_link_opens_primary():
    primary = MockTransport(name="usb")
    link = Link(transport=primary, protocol=AsciiBracketProtocol(), name="mc01")
    link.open()
    assert link.connected
    assert "usb" in link.descriptor()
    link.close()


def test_link_falls_back_to_relay():
    relay = MockTransport(name="jetson-relay")
    link = Link(
        transport=_FailingTransport(name="usb"),
        protocol=AsciiBracketProtocol(),
        relay=relay,
        name="mc01",
    )
    link.open()
    assert link.connected
    assert "via relay" in link.descriptor()
    link.send({"header": "MJ", "args": [90, 100, 10]})
    assert relay.writes == [b"MJ[90,100,10]\n"]
    link.close()


def test_link_raises_when_every_path_fails():
    link = Link(
        transport=_FailingTransport(name="usb"),
        protocol=AsciiBracketProtocol(),
        relay=_FailingTransport(name="relay"),
        name="mc01",
    )
    with pytest.raises(ConnectionError, match="mc01"):
        link.open()
    assert not link.connected
    assert "port gone" in link.last_error


def test_link_send_requires_open():
    link = Link(transport=MockTransport(), protocol=AsciiBracketProtocol())
    with pytest.raises(ConnectionError):
        link.send("CN")


def test_link_rx_thread_delivers_events():
    mock = MockTransport(name="usb")
    seen: list = []
    link = Link(
        transport=mock,
        protocol=AsciiBracketProtocol(),
        on_event=seen.append,
        rx_poll_s=0.005,
        name="mc01",
    )
    link.open()
    try:
        mock.inject(b"--- STATUS UPDATE ---\n")
        deadline = time.monotonic() + 2.0
        while not seen and time.monotonic() < deadline:
            time.sleep(0.005)
        assert seen, "RX thread never delivered the injected heartbeat"
        assert seen[0].kind == "telemetry"
        assert link.health()["connected"] is True
        assert link.health()["last_rx_age_s"] >= 0.0
    finally:
        link.close()


def test_link_rx_survives_handler_exception():
    mock = MockTransport(name="usb")
    seen: list = []

    def flaky(event):
        if not seen:
            seen.append(event)
            raise RuntimeError("handler bug")
        seen.append(event)

    link = Link(
        transport=mock, protocol=AsciiBracketProtocol(),
        on_event=flaky, rx_poll_s=0.005,
    )
    link.open()
    try:
        mock.inject(b"one\n")
        mock.inject(b"two\n")
        deadline = time.monotonic() + 2.0
        while len(seen) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(seen) == 2
        assert "handler" in link.last_error
    finally:
        link.close()


# ── package loader ─────────────────────────────────────────────────────


_TOPOLOGY = """
package: testbot
requires_framework: ">=0.6"
display_name: Test Bot

controllers:
  mc01:
    node: motor
    adapter: testbot.adapters.mc01:Adapter
    link:
      transport: serial
      port: /dev/cu.usbserial-110
      baud: 115200
      protocol: ascii_bracket
      relay:
        transport: zmq_req
        endpoint: tcp://192.168.2.2:5556
        target: motion
    simulated: true
    heartbeat_expect_s: 30
  avc01:
    node: light
    adapter: testbot.adapters.avc01:Adapter
    link:
      transport: serial
      port: /dev/cu.usbmodem1
      protocol: ascii_bracket
    simulated: true

capabilities:
  - {name: motion.move, controller: mc01, tier: HARDWARE,
     schema: fake_robot_caps:MoveArgs}
  - {name: motion.stop, controller: mc01, tier: HARDWARE,
     schema: fake_robot_caps:EmptyArgs, allow_when_latched: true}
  - {name: lights.set_mode, controller: avc01, tier: WRITE_LOCAL,
     schema: fake_robot_caps:ModeArgs}
  - {name: telemetry.read, controller: "*", tier: READ_ONLY,
     schema: fake_robot_caps:EmptyArgs}

safety:
  estop_scope: [mc01]
  firmware_watchdog_required: true
"""


def _write_topology(tmp_path, text=_TOPOLOGY):
    pkg = tmp_path / "testbot"
    pkg.mkdir(exist_ok=True)
    (pkg / "topology.yaml").write_text(text, encoding="utf-8")
    return pkg


def test_load_package_happy_path(tmp_path):
    spec = load_package(_write_topology(tmp_path))
    assert spec.package == "testbot"
    assert set(spec.controllers) == {"mc01", "avc01"}
    assert spec.controllers["mc01"].link.relay.target == "motion"
    assert spec.controllers["mc01"].simulated is True
    assert [c.name for c in spec.capabilities] == [
        "motion.move", "motion.stop", "lights.set_mode", "telemetry.read",
    ]
    assert spec.safety.estop_scope == ["mc01"]


def test_load_package_accepts_yaml_file_path(tmp_path):
    pkg = _write_topology(tmp_path)
    assert load_package(pkg / "topology.yaml").package == "testbot"


def test_load_package_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_package(tmp_path / "nope")


def test_load_package_refuses_unknown_field(tmp_path):
    bad = _TOPOLOGY.replace("display_name:", "displayname_typo:")
    with pytest.raises(ValueError):
        load_package(_write_topology(tmp_path, bad))


def test_load_package_refuses_unknown_controller_ref(tmp_path):
    bad = _TOPOLOGY.replace("controller: avc01", "controller: ghost01")
    with pytest.raises(ValueError, match="ghost01"):
        load_package(_write_topology(tmp_path, bad))


def test_load_package_refuses_dotless_capability(tmp_path):
    bad = _TOPOLOGY.replace("name: telemetry.read", "name: telemetry_read")
    with pytest.raises(ValueError, match="subsystem.action"):
        load_package(_write_topology(tmp_path, bad))


def test_load_package_refuses_unknown_estop_scope(tmp_path):
    bad = _TOPOLOGY.replace("estop_scope: [mc01]", "estop_scope: [ghost01]")
    with pytest.raises(ValueError, match="ghost01"):
        load_package(_write_topology(tmp_path, bad))


def test_load_package_framework_version_gate(tmp_path):
    too_new = _TOPOLOGY.replace('">=0.6"', '">=99.0"')
    with pytest.raises(RuntimeError, match="refusing to load"):
        load_package(_write_topology(tmp_path, too_new))
    bad_form = _TOPOLOGY.replace('">=0.6"', '"==0.6"')
    with pytest.raises(ValueError, match=">=X.Y"):
        load_package(_write_topology(tmp_path, bad_form))


def test_build_transport_simulated_overrides_serial():
    spec = LinkSpec(transport="serial", port="/dev/none")
    assert isinstance(build_transport(spec, simulated=True), MockTransport)


def test_build_transport_validation():
    with pytest.raises(ValueError, match="port"):
        build_transport(LinkSpec(transport="serial"), simulated=False)
    with pytest.raises(ValueError, match="endpoint"):
        build_transport(LinkSpec(transport="zmq_req"), simulated=False)
    with pytest.raises(ValueError, match="unknown transport"):
        build_transport(LinkSpec(transport="carrier_pigeon"), simulated=False)


def test_build_link_simulated_skips_relay(tmp_path):
    spec = load_package(_write_topology(tmp_path))
    link = build_link("mc01", spec.controllers["mc01"])
    link.open()
    assert link.connected
    assert "via relay" not in link.descriptor()
    link.close()


def test_resolve_ref_contract():
    with pytest.raises(ValueError, match="module:attr"):
        resolve_ref("no_colon_here", package="testbot")
    fn = resolve_ref("jaeger_os.hardware.protocol:make_protocol",
                     package="testbot")
    assert fn is make_protocol
    with pytest.raises(ImportError, match="no attribute"):
        resolve_ref("jaeger_os.hardware.protocol:missing", package="testbot")


# ── e-stop latch ───────────────────────────────────────────────────────


def test_estop_engage_runs_stops_once_and_latches():
    latch = EStopLatch()
    stops: list[str] = []
    latch.register_stop("mc01", lambda: stops.append("mc01"))
    latch.engage("test", source="operator")
    latch.engage("again", source="agent")     # already latched — no re-run
    assert latch.engaged
    assert stops == ["mc01"]
    s = latch.status()
    assert s["reason"] == "test" and s["source"] == "operator"
    assert "e-stop latched" in latch.refusal()


def test_estop_release_is_operator_only():
    latch = EStopLatch()
    latch.engage("test")
    with pytest.raises(PermissionError):
        latch.release(source="agent")
    assert latch.engaged
    latch.release(source="operator")
    assert not latch.engaged


def test_estop_bad_stop_callback_never_blocks_others():
    latch = EStopLatch()
    stops: list[str] = []
    latch.register_stop("bad", lambda: 1 / 0)
    latch.register_stop("good", lambda: stops.append("good"))
    latch.engage("test")
    assert stops == ["good"]


def test_estop_propagates_over_bus():
    bus = InProcBus()
    try:
        a = EStopLatch(bus)
        b = EStopLatch(bus)
        a.engage("button pressed", source="button")
        deadline = time.monotonic() + 2.0
        while not b.engaged and time.monotonic() < deadline:
            time.sleep(0.005)
        assert b.engaged
        # Non-operator release on the wire is ignored.
        bus.publish(topics.EStop(engaged=False, source="agent"))
        time.sleep(0.05)
        assert b.engaged
        a.release(source="operator")
        deadline = time.monotonic() + 2.0
        while b.engaged and time.monotonic() < deadline:
            time.sleep(0.005)
        assert not b.engaged
    finally:
        bus.close()


# ── permissions: HARDWARE tier rides the confirmation flow ────────────


def test_hardware_tier_routes_through_confirmation():
    req = PermissionRequest(
        tier=PermissionTier.HARDWARE, skill="hardware.testbot",
        operation="motion.move", summary="",
    )
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        PermissionPolicy(confirmation=AllowAllProvider()).check(req)  # no raise
    with pytest.raises(PermissionDenied):
        PermissionPolicy(confirmation=DenyAllProvider()).check(req)


# ── capability registration + dispatch ─────────────────────────────────


def _install_fake_caps_module():
    """A package's capabilities module, faked into sys.modules so the
    topology's ``fake_robot_caps:…`` refs resolve."""
    mod = types.ModuleType("fake_robot_caps")

    class MoveArgs(BaseModel):
        """Move both joints."""
        a1: int = Field(ge=40, le=150, description="joint 1 angle")
        a2: int = Field(ge=70, le=105, description="joint 2 angle")
        speed: int = Field(default=10, ge=1, le=100)

    class ModeArgs(BaseModel):
        """Set LED mode."""
        mode: int = Field(ge=0, le=9)

    class EmptyArgs(BaseModel):
        """No arguments."""

    calls: list[tuple] = []

    def move(ctx, args):
        calls.append(("move", ctx.controller, args.a1, args.a2))
        ctx.link.send({"header": "MJ", "args": [args.a1, args.a2, args.speed]})
        return {"sent": f"MJ[{args.a1},{args.a2},{args.speed}]"}

    def stop(ctx, args):  # noqa: ARG001
        calls.append(("stop", ctx.controller))
        return {"stopped": True}

    def set_mode(ctx, args):
        calls.append(("set_mode", args.mode))
        return {"mode": args.mode}

    def read(ctx, args):  # noqa: ARG001
        calls.append(("read",))
        return {"telemetry": "cached"}

    def boom(ctx, args):  # noqa: ARG001
        raise RuntimeError("solenoid jammed")

    mod.MoveArgs = MoveArgs
    mod.ModeArgs = ModeArgs
    mod.EmptyArgs = EmptyArgs
    mod.move = move
    mod.stop = stop
    mod.set_mode = set_mode
    mod.read = read
    mod.boom = boom
    mod.calls = calls
    sys.modules["fake_robot_caps"] = mod
    return mod


@pytest.fixture
def fake_package(tmp_path):
    mod = _install_fake_caps_module()
    spec = load_package(_write_topology(tmp_path))
    links = {
        name: build_link(name, ctrl)
        for name, ctrl in spec.controllers.items()
    }
    for link in links.values():
        link.open()
    estop = EStopLatch()
    defs = register_package_capabilities(spec, links=links, estop=estop)
    policy = PermissionPolicy(confirmation=AllowAllProvider())
    with use_policy(policy):
        yield types.SimpleNamespace(
            spec=spec, links=links, estop=estop, defs=defs, mod=mod,
        )
    for d in defs:
        unregister_tool(d.name)
    for link in links.values():
        link.close()
    sys.modules.pop("fake_robot_caps", None)


def test_capabilities_group_into_umbrella_tools(fake_package):
    names = sorted(d.name for d in fake_package.defs)
    assert names == ["lights", "motion", "telemetry"]
    motion = get_tool("motion")
    assert motion.beta is True
    assert motion.dangerous is True
    assert motion.side_effect == "hardware"
    assert motion.toolset == "hardware"
    assert motion.permission_tier == "HARDWARE"
    assert get_tool("telemetry").side_effect == "read"
    assert get_tool("lights").side_effect == ""
    # Merged model: action literal + per-action fields, optional.
    fields = motion.args_model.model_fields
    assert "action" in fields and "a1" in fields and "speed" in fields
    assert "move" in str(fields["action"].annotation)


def test_dispatch_happy_path_sends_brackets(fake_package):
    result = get_tool("motion").fn(action="move", a1=90, a2=100)
    assert result["ok"] is True
    assert result["sent"] == "MJ[90,100,10]"
    mc01_wire = fake_package.links["mc01"]._active.writes
    assert mc01_wire == [b"MJ[90,100,10]\n"]


def test_dispatch_unknown_action(fake_package):
    result = get_tool("motion").fn(action="moonwalk")
    # Registry-validated calls can't reach here with a bad literal,
    # but the dispatcher still guards its own contract.
    assert result["ok"] is False and "unknown action" in result["error"]


def test_dispatch_validates_against_action_schema(fake_package):
    result = get_tool("motion").fn(action="move", a1=999, a2=100)
    assert result["ok"] is False
    assert "invalid arguments" in result["error"]
    assert result["retryable"] is False


def test_dispatch_offline_controller_fails_closed(fake_package):
    fake_package.links["mc01"].close()
    result = get_tool("motion").fn(action="move", a1=90, a2=100)
    assert result["ok"] is False
    assert "offline" in result["error"]
    assert result["retryable"] is True
    # check_fn mirrors it: motion unavailable, lights still fine.
    assert get_tool("motion").is_available() is False
    assert get_tool("lights").is_available() is True


def test_dispatch_estop_refuses_hardware_but_not_reads(fake_package):
    fake_package.estop.engage("test stop", source="operator")
    moved = get_tool("motion").fn(action="move", a1=90, a2=100)
    assert moved["ok"] is False and "e-stop latched" in moved["error"]
    # allow_when_latched: motion.stop still works DURING the latch.
    stopped = get_tool("motion").fn(action="stop")
    assert stopped["ok"] is True
    # Non-HARDWARE tiers keep working (lights, telemetry).
    assert get_tool("lights").fn(action="set_mode", mode=3)["ok"] is True
    assert get_tool("telemetry").fn(action="read")["ok"] is True


def test_dispatch_policy_denial_is_typed_not_raised(fake_package):
    with use_policy(PermissionPolicy(confirmation=DenyAllProvider())):
        result = get_tool("motion").fn(action="move", a1=90, a2=100)
    assert result["ok"] is False
    assert "confirmation refused" in result["error"]
    assert result["retryable"] is False


def test_dispatch_handler_exception_stays_typed(fake_package, tmp_path):
    # Point motion.move at the raising handler via an explicit ref.
    bad = _TOPOLOGY.replace(
        "schema: fake_robot_caps:MoveArgs}",
        "schema: fake_robot_caps:MoveArgs, handler: fake_robot_caps:boom}",
    )
    spec = load_package(_write_topology(tmp_path, bad))
    defs = register_package_capabilities(
        spec, links=fake_package.links, estop=None,
    )
    try:
        result = get_tool("motion").fn(action="move", a1=90, a2=100)
        assert result["ok"] is False
        assert "solenoid jammed" in result["error"]
        assert result["retryable"] is True
    finally:
        for d in defs:
            unregister_tool(d.name)


def test_registration_refuses_unknown_tier(fake_package, tmp_path):
    bad = _TOPOLOGY.replace("tier: WRITE_LOCAL", "tier: SUPER_SAFE")
    spec = load_package(_write_topology(tmp_path, bad))
    with pytest.raises(ValueError, match="SUPER_SAFE"):
        register_package_capabilities(
            spec, links=fake_package.links, estop=None,
        )


def test_registration_refuses_conflicting_field_types(fake_package, tmp_path):
    mod = fake_package.mod

    class ClashArgs(BaseModel):
        a1: str = ""          # conflicts with MoveArgs.a1: int

    mod.ClashArgs = ClashArgs
    mod.clash = lambda ctx, args: {}
    bad = _TOPOLOGY.replace(
        "  - {name: motion.stop",
        "  - {name: motion.clash, controller: mc01, tier: HARDWARE,\n"
        "     schema: fake_robot_caps:ClashArgs}\n"
        "  - {name: motion.stop",
    )
    spec = load_package(_write_topology(tmp_path, bad))
    with pytest.raises(ValueError, match="conflicting types"):
        register_package_capabilities(
            spec, links=fake_package.links, estop=None,
        )


def test_umbrella_registered_even_when_all_links_down(tmp_path):
    """Plan §2.6: declared-but-absent registers anyway; availability
    tracks health."""
    _install_fake_caps_module()
    spec = load_package(_write_topology(tmp_path))
    links = {
        name: build_link(name, ctrl)
        for name, ctrl in spec.controllers.items()
    }   # never opened
    defs = register_package_capabilities(spec, links=links, estop=None)
    try:
        assert has_tool("motion")
        assert get_tool("motion").is_available() is False
        with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
            result = get_tool("motion").fn(action="move", a1=90, a2=100)
        assert result["ok"] is False and "offline" in result["error"]
    finally:
        for d in defs:
            unregister_tool(d.name)
        sys.modules.pop("fake_robot_caps", None)
