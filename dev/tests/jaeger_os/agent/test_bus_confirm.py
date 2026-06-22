"""Bus-backed permission confirmation — the interactive request/response
provider for windowed/remote surfaces.

The provider publishes an AgentRequest and blocks the turn until a surface
answers with AgentResponse. Pin: allow→True, deny→False, "always" grants
the skill (asks once), timeout→deny (fail-safe).
"""

from __future__ import annotations

import time
import types

from jaeger_os.agent.loop.bus_confirm import BusConfirmationProvider
from jaeger_os.core.messages import AgentRequest, AgentResponse
from jaeger_os.transport.inproc_bus import InProcBus


def _req(skill: str, op: str):
    return types.SimpleNamespace(skill=skill, operation=op, summary="")


def test_allow_returns_true():
    bus = InProcBus()
    prov = BusConfirmationProvider(bus, timeout_s=5)
    bus.subscribe(AgentRequest.topic,
                  lambda r: bus.publish(AgentResponse(id=r.id, answer="allow")))
    assert prov.confirm(_req("files", "write_file")) is True


def test_deny_returns_false():
    bus = InProcBus()
    prov = BusConfirmationProvider(bus, timeout_s=5)
    bus.subscribe(AgentRequest.topic,
                  lambda r: bus.publish(AgentResponse(id=r.id, answer="deny")))
    assert prov.confirm(_req("shell", "run")) is False


def test_always_grants_the_skill_for_the_session():
    bus = InProcBus()
    prov = BusConfirmationProvider(bus, timeout_s=5)
    asks: list[str] = []

    def once(r):
        asks.append(r.id)
        bus.publish(AgentResponse(id=r.id, answer="always"))

    bus.subscribe(AgentRequest.topic, once)
    assert prov.confirm(_req("vision", "screenshot")) is True   # asks
    assert prov.confirm(_req("vision", "screenshot")) is True   # granted, no ask
    time.sleep(0.1)
    assert len(asks) == 1


def test_timeout_fails_safe_to_deny():
    bus = InProcBus()
    prov = BusConfirmationProvider(bus, timeout_s=0.3)   # nobody answers
    assert prov.confirm(_req("net", "fetch")) is False
