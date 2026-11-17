"""Mid-turn approvals route to the channel the turn came from.

Before: the BusConfirmationProvider published an AgentRequest, but only the
desktop window answered it — a remote Telegram user had no way to approve, so
the turn hung. Now _run_turn tags the confirm session per turn, and the
Telegram bridge answers requests for its own chats.
"""

import threading


def test_tag_confirm_session_sets_provider_session() -> None:
    import jaeger_ai.main as m
    from jaeger_agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.transport import InProcBus
    from jaeger_os.core.safety.permissions import current_policy

    bus = InProcBus()
    prov = BusConfirmationProvider(bus)
    pol = current_policy()
    saved = pol.confirmation
    pol.confirmation = prov
    try:
        m._tag_confirm_session("telegram:999")
        assert prov.current_session == "telegram:999"
    finally:
        pol.confirmation = saved
        bus.close()


def test_confirm_round_trips_via_a_channel_responder() -> None:
    """The exact bus mechanism the Telegram bridge plugs into: confirm()
    publishes an AgentRequest tagged with the session; a responder for that
    session publishes an AgentResponse; confirm() unblocks with the answer."""
    from jaeger_agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.transport import InProcBus
    from jaeger_agent.core.messages import AgentRequest, AgentResponse

    from jaeger_os.core.safety import session_trust
    bus = InProcBus()
    prov = BusConfirmationProvider(bus, timeout_s=3.0)
    prov.current_session = "telegram:55"
    session_trust.mark_session("telegram:55", True)   # certified owner → prompts (vs auto-deny)

    def responder(req) -> None:   # simulate the telegram bridge answering
        if getattr(req, "session", "") == "telegram:55":
            bus.publish(AgentResponse(id=req.id, answer="allow", session=req.session))

    bus.subscribe(AgentRequest.topic, responder)

    req = type("R", (), {"skill": "messaging", "operation": "send", "summary": ""})()
    out: dict = {}
    t = threading.Thread(target=lambda: out.update(ok=prov.confirm(req)))
    t.start(); t.join(timeout=5.0)
    assert out.get("ok") is True
    bus.close()


