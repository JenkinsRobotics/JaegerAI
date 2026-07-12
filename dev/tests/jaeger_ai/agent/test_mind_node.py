"""MindNode / make_mind_node — the Mind wrapped as a supervised Node.

0.9 step 3 (mind-as-module, dev/docs/vision/THREE_TIER_STRUCTURE.md):
these tests exercise the factory under the supervisor's Node contract
WITHOUT loading a real model — ``jaeger_os.main.boot_for_tui`` is
monkeypatched to return a stub ``TUIBootResult`` around a fake client,
the same "no model, no GUI" style ``dev/tests/jaeger_os/agent/
test_bridge.py`` already uses for :class:`AgentBridge` itself (which
``MindNode.setup()`` constructs). Discovery + availability are checked
against the REAL ``jaeger_os/agent/module.yaml`` — no monkeypatching
needed there since ``llama_cpp`` is an actual project dependency.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from jaeger_ai.agent.loop.mind_node import MindNode, make_mind_node
from jaeger_os.nodes.base import NodeState
from jaeger_os.transport import InProcBus


@dataclasses.dataclass
class _FakeBoot:
    client: Any
    layout: Any = None
    cleanup_calls: list = dataclasses.field(default_factory=list)

    def cleanup(self) -> None:
        self.cleanup_calls.append(True)


def _fake_boot_for_tui(**_: Any) -> _FakeBoot:
    return _FakeBoot(client=object())


def test_make_mind_node_returns_a_node_with_defaults():
    bus = InProcBus()
    node = make_mind_node(bus, {})
    assert isinstance(node, MindNode)
    assert node.name == "mind"
    assert node.state == NodeState.INIT
    bus.close()


def test_make_mind_node_reads_config_overrides():
    bus = InProcBus()
    node = make_mind_node(
        bus, {"instance_name": "shake", "with_memory": False, "warmup": True})
    assert node._instance_name == "shake"
    assert node._with_memory is False
    assert node._warmup is True
    bus.close()


def test_mind_node_setup_boots_on_a_stub_client_no_real_model(monkeypatch):
    """setup() calls boot_for_tui() + starts an AgentBridge — with
    boot_for_tui monkeypatched to a stub, no model ever loads and the
    node still reaches RUNNING via the same run() state machine every
    other Node uses."""
    import jaeger_ai.main as main_mod

    monkeypatch.setattr(main_mod, "boot_for_tui", _fake_boot_for_tui)

    bus = InProcBus()
    node = MindNode(bus=bus, name="mind-test")
    try:
        node.setup()
        assert node.boot is not None
        assert node.bridge is not None
        assert node.bridge.client is not None
        h = node.health()
        assert h["state"] == "idle"       # AgentBridge's own idle state
        assert "turns" in h
    finally:
        node.teardown()
        bus.close()


def test_mind_node_teardown_stops_bridge_and_calls_cleanup(monkeypatch):
    import jaeger_ai.main as main_mod

    fake_boot = _FakeBoot(client=object())
    monkeypatch.setattr(main_mod, "boot_for_tui", lambda **_: fake_boot)

    bus = InProcBus()
    node = MindNode(bus=bus, name="mind-test")
    node.setup()
    node.teardown()
    assert fake_boot.cleanup_calls == [True]
    bus.close()


def test_mind_node_runs_the_full_node_lifecycle_via_run(monkeypatch):
    """The exact path ThreadHandle.start() drives: run() on a worker
    thread, polling for RUNNING/FAILED — proves MindNode satisfies the
    Node contract end to end, not just its own methods in isolation."""
    import threading
    import time

    import jaeger_ai.main as main_mod

    monkeypatch.setattr(main_mod, "boot_for_tui", _fake_boot_for_tui)

    bus = InProcBus()
    node = MindNode(bus=bus, name="mind-lifecycle")
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if node.state in (NodeState.RUNNING, NodeState.FAILED):
                break
            time.sleep(0.01)
        assert node.state == NodeState.RUNNING
    finally:
        node.stop()
        thread.join(timeout=3.0)
        assert node.state == NodeState.STOPPED
        bus.close()


def test_mind_slot_availability_follows_the_standard_probe():
    """The generic slot-readiness probe (jaeger_os/agent/availability.py
    — the same function messaging's ANY-OF gate uses) reports the mind
    slot ready, driven purely by requires_libraries against the REAL
    jaeger_os/agent/module.yaml — no special-casing for this slot."""
    from jaeger_ai.agent.availability import _slot_ready, clear_availability_caches

    clear_availability_caches()
    assert _slot_ready("mind") is True
