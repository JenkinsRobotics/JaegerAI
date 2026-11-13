"""OpenAI-style handoff (Team mode): the teammate takes the next turn after a completed transfer."""
from types import SimpleNamespace

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.runtime.collaboration import HELPER_DENIED_TOOLS


class _Store:
    def __init__(self, status):
        self.status = status
        self.admitted = []

    def get_request(self, rid):
        return {"request_id": rid, "status": self.status}

    def admit_request(self, sid, text, *, request_id, requested):
        self.admitted.append((sid, text, request_id, requested))
        return {"turn_id": "t2", "request_id": request_id, "accepted": True}


def _gateway(status):
    started = []
    gw = SimpleNamespace(store=_Store(status))
    gw._pending_transfers = {"r1": {"session_id": "s1", "to_agent_id": "native:design", "display": "Design & Style",
                                    "from_agent_id": "native:jaeger", "reason": "UI review"}}
    gw._start_admitted_turn = lambda admitted, sid, text: started.append((sid, admitted["request_id"]))
    return gw, started


def test_completed_transfer_starts_the_teammate_turn_once():
    gw, started = _gateway("completed")
    JaegerGatewayApp._continue_after_transfer(gw, "r1")
    JaegerGatewayApp._continue_after_transfer(gw, "r1")
    assert started == [("s1", "r1-transfer")]
    assert "Design & Style" in gw.store.admitted[0][1]
    assert gw.store.admitted[0][3]["options"]["source"] == "handoff"


def test_stopped_turn_does_not_continue():
    gw, started = _gateway("cancelled")
    JaegerGatewayApp._continue_after_transfer(gw, "r1")
    assert started == []


def test_helpers_can_never_transfer_the_chat():
    assert "transfer_to_agent" in HELPER_DENIED_TOOLS
