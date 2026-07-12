"""Per-session admin trust — the one-owner model.

Local surfaces are the owner (admin); remote messaging sessions are non-admin
until certified, and an UNMARKED remote session fails safe (non-admin). The
permission provider auto-denies tier-gated actions for non-admin sessions
without ever prompting — so a stranger on the bot can't elevate.
"""

import threading
import time


def test_local_sessions_are_admin_by_default() -> None:
    from jaeger_os.core.safety.session_trust import forget_session, is_admin_session
    for s in ("gui-abc123", "voice", "", "deepthink-1"):
        forget_session(s)
        assert is_admin_session(s) is True


def test_remote_sessions_fail_safe_until_marked() -> None:
    from jaeger_os.core.safety.session_trust import (
        forget_session, is_admin_session, mark_session)
    forget_session("telegram:999")
    assert is_admin_session("telegram:999") is False     # unmarked remote → non-admin
    mark_session("telegram:999", True)
    assert is_admin_session("telegram:999") is True       # certified
    mark_session("telegram:999", False)
    assert is_admin_session("telegram:999") is False
    forget_session("telegram:999")


def _req():
    return type("R", (), {"skill": "messaging", "operation": "send", "summary": ""})()


def test_confirm_auto_denies_non_admin_and_never_prompts() -> None:
    from jaeger_ai.agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.transport import InProcBus
    from jaeger_ai.core.messages import AgentRequest
    from jaeger_os.core.safety.session_trust import forget_session

    forget_session("telegram:guest")              # the global registry is shared
    bus = InProcBus()
    asked: list = []
    bus.subscribe(AgentRequest.topic, lambda m: asked.append(m.session))
    prov = BusConfirmationProvider(bus, timeout_s=1.0)
    prov.current_session = "telegram:guest"       # uncertified remote → non-admin

    result = prov.confirm(_req())
    time.sleep(0.1)
    assert result is False                         # denied
    assert asked == []                             # NEVER prompted (no request published)
    bus.close()


def test_confirm_prompts_an_admin_session() -> None:
    from jaeger_ai.agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.transport import InProcBus
    from jaeger_ai.core.messages import AgentRequest, AgentResponse

    bus = InProcBus()
    asked: list = []

    def responder(req) -> None:
        asked.append(req.session)
        bus.publish(AgentResponse(id=req.id, answer="deny", session=req.session))

    bus.subscribe(AgentRequest.topic, responder)
    prov = BusConfirmationProvider(bus, timeout_s=3.0)
    prov.current_session = "gui-xyz"               # local = admin → normal flow

    out: dict = {}
    t = threading.Thread(target=lambda: out.update(r=prov.confirm(_req())))
    t.start(); t.join(timeout=4.0)
    assert asked == ["gui-xyz"]                    # admin session WAS prompted
    assert out.get("r") is False                   # (we answered "deny")
    bus.close()


def test_certify_admin_tool_registered() -> None:
    from jaeger_os.core.tools import tool_registry as R
    import jaeger_ai.main as m
    m._register_builtins(object())
    assert "certify_admin" in {t.name for t in R.get_tools()}
