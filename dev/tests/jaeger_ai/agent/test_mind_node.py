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












def test_mind_slot_availability_follows_the_standard_probe():
    """The generic slot-readiness probe (jaeger_os/agent/availability.py
    — the same function messaging's ANY-OF gate uses) reports the mind
    slot ready, driven purely by requires_libraries against the REAL
    jaeger_os/agent/module.yaml — no special-casing for this slot."""
    from jaeger_agent.core.availability import _slot_ready, clear_availability_caches

    clear_availability_caches()
    assert _slot_ready("mind") is True
