"""M3 unit proof: voice fast lane routes conversational turns to DIRECT_RESPONSE.

Run: PYTHONPATH=. python3 -m pytest dev/tests/jaeger_ai/core/test_voice_fast_lane.py -q
"""
from __future__ import annotations

import time

from jaeger_ai.core.entity.events import JaegerEvent
from jaeger_ai.core.entity.executive import ExecutiveStrategySelector
from jaeger_ai.core.entity.self_state import SelfState
from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.cognition_router import CognitiveStrategy


def _state() -> SelfState:
    return SelfState(identity=EntityIdentity.create_default("test-jaeger"))


def _event(text: str, *, source: str = "voice", fast_lane: bool = True) -> JaegerEvent:
    return JaegerEvent.human_message(
        text, source=source, session_id="voice-test",
        metadata={"fast_lane": True} if fast_lane else {},
    )


def test_voice_conversational_turn_takes_direct_lane():
    ev = _event("hey, how's it going?")
    assert ev.payload.get("source") == "voice"
    assert ev.payload.get("fast_lane") is True
    dec = ExecutiveStrategySelector.select_strategy(ev, _state())
    assert dec.strategy == CognitiveStrategy.DIRECT_RESPONSE, dec.reason


def test_voice_turn_asking_for_work_still_gets_react():
    ev = _event("run the test suite for the gateway")
    dec = ExecutiveStrategySelector.select_strategy(ev, _state())
    assert dec.strategy != CognitiveStrategy.DIRECT_RESPONSE, dec.reason


def test_non_voice_turn_unchanged():
    ev = JaegerEvent.human_message("hey, how's it going?", source="webui", session_id="s1")
    dec = ExecutiveStrategySelector.select_strategy(ev, _state())
    # a plain chat message must NOT be forced onto the fast lane
    assert dec.strategy != CognitiveStrategy.DIRECT_RESPONSE or ev.payload.get("fast_lane")


def test_gateway_executes_conversational_voice_on_existing_model_lane():
    from types import SimpleNamespace
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    runtime = SimpleNamespace(executive_selector=ExecutiveStrategySelector, current_state=_state())
    prepared = SimpleNamespace(event=_event("Hello Jaeger", source="gateway"))
    assert JaegerGatewayApp._voice_direct_lane(runtime, prepared, fast_lane=True)
    assert not JaegerGatewayApp._voice_direct_lane(runtime, prepared, fast_lane=False)
    work = SimpleNamespace(event=_event("Run the tests", source="gateway"))
    assert not JaegerGatewayApp._voice_direct_lane(runtime, work, fast_lane=True)


def test_gateway_keeps_owner_execution_when_voice_strategy_is_unavailable():
    from types import SimpleNamespace
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    assert not JaegerGatewayApp._voice_direct_lane(SimpleNamespace(), None, fast_lane=True)
    assert not JaegerGatewayApp._voice_direct_lane(SimpleNamespace(), SimpleNamespace(event=None), fast_lane=True)
