"""Stop while the lead waits on a helper: the tool returns at once as cancelled."""
import threading

from jaeger_agent.core.cancellation import turn_cancellation
from jaeger_agent.tools import call_agent


def test_turn_stopped_reads_the_bound_cancellation():
    event = threading.Event()
    with turn_cancellation(event):
        assert call_agent._turn_stopped() is False
        event.set()
        assert call_agent._turn_stopped() is True
    assert call_agent._turn_stopped() is False


def test_stopped_result_is_a_cancelled_failure():
    out = call_agent._stopped_result("handoff_1", helper="Design & Style")
    assert out["ok"] is False and out["status"] == "cancelled"
    assert out["handoff_id"] == "handoff_1"
