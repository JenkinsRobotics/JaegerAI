"""Mid-turn approvals route to the channel the turn came from.

Before: the BusConfirmationProvider published an AgentRequest, but only the
desktop window answered it — a remote Telegram user had no way to approve, so
the turn hung. Now _run_turn tags the confirm session per turn, and the
Telegram bridge answers requests for its own chats.
"""

import asyncio
import threading


def test_tag_confirm_session_sets_provider_session() -> None:
    import jaeger_os.main as m
    from jaeger_os.agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.app.bus.inproc import InProcBus
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
    from jaeger_os.agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.app.bus.inproc import InProcBus
    from jaeger_os.core.messages import AgentRequest, AgentResponse

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


def test_telegram_bridge_routes_request_to_awaiting(monkeypatch) -> None:
    """_on_agent_request marks the chat awaiting for a telegram session and
    ignores other sessions (so it doesn't steal the desktop's approvals)."""
    from jaeger_os.plugins.telegram.bridge import TelegramBridge

    def _fake_schedule(coro, loop):   # don't run the async send; avoid warnings
        coro.close()
        return None

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _fake_schedule)

    b = TelegramBridge(lambda *a, **k: "", token="x", bus=object())
    b._app = type("A", (), {"bot": None})()
    b._loop = object()   # truthy so _on_agent_request proceeds

    req = type("R", (), {"session": "telegram:77", "id": "rid1",
                         "prompt": "Allow?", "options": ("allow", "deny")})()
    b._on_agent_request(req)
    assert b._awaiting.get(77) == "rid1"

    b._awaiting.clear()
    b._on_agent_request(type("R", (), {"session": "gui-abc", "id": "x"})())
    assert b._awaiting == {}   # non-telegram session ignored
