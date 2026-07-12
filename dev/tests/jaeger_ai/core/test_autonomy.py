"""Autonomy modes — how autonomously the agent executes an agreed task.

Covers the module (set/get/default), the confirm() chokepoint honoring each
mode, and the cross-channel slash parser.
"""

from types import SimpleNamespace

from jaeger_ai.core.runtime import autonomy


def test_module_default_set_and_unknown() -> None:
    try:
        assert autonomy.current_autonomy() == autonomy.DEFAULT == "scoped"
        assert set(autonomy.list_autonomy()) == {"ask", "scoped", "auto"}
        assert autonomy.set_autonomy("auto")["ok"]
        assert autonomy.current_autonomy() == "auto"
        bad = autonomy.set_autonomy("nope")
        assert not bad["ok"] and autonomy.current_autonomy() == "auto"   # unchanged
        info = autonomy.autonomy_info()
        assert info["autonomy"] == "auto" and "options" in info and info["description"]
    finally:
        autonomy.set_autonomy(autonomy.DEFAULT)


class _FakeBus:
    def __init__(self) -> None:
        self.published: list = []

    def subscribe(self, topic, cb) -> None:  # noqa: ANN001
        pass

    def publish(self, msg) -> None:  # noqa: ANN001
        self.published.append(msg)


def test_confirm_honors_each_mode() -> None:
    from jaeger_ai.agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.core.safety import session_trust

    sess = "test:autonomy-gate"
    session_trust.mark_session(sess, True)                  # admin — gets past the trust gate
    try:
        bus = _FakeBus()
        p = BusConfirmationProvider(bus, timeout_s=0.05)    # tiny timeout: a prompt → deny fast
        p.current_session = sess
        req = SimpleNamespace(skill="files", operation="delete_file", summary="")

        autonomy.set_autonomy("auto")
        assert p.confirm(req) is True
        assert bus.published == []                          # auto never prompts

        autonomy.set_autonomy("scoped")
        p._granted_skills.add("files")
        assert p.confirm(req) is True                       # granted scope runs quiet
        assert bus.published == []

        autonomy.set_autonomy("ask")
        assert p.confirm(req) is False                      # ask ignores the grant → prompts → no answer → deny
        assert bus.published                                # it DID surface a prompt
    finally:
        autonomy.set_autonomy(autonomy.DEFAULT)
        session_trust.forget_session(sess)


def test_slash_parser() -> None:
    from jaeger_ai.plugins import _messaging
    try:
        assert _messaging.autonomy_command("/mode") == {}            # not ours → falls through to /mode
        assert _messaging.autonomy_command("hello") == {}
        r = _messaging.autonomy_command("/auto")
        assert autonomy.current_autonomy() == "auto" and "auto" in r["reply"]
        r = _messaging.autonomy_command("/autonomy")                 # bare → status
        assert "auto" in r["reply"] and "options" in r["reply"]
        r = _messaging.autonomy_command("/autonomy bogus")
        assert "✗" in r["reply"] and autonomy.current_autonomy() == "auto"   # unchanged on bad target
        _messaging.autonomy_command("/scoped")
        assert autonomy.current_autonomy() == "scoped"
    finally:
        autonomy.set_autonomy(autonomy.DEFAULT)


def test_tools_registered() -> None:
    from jaeger_os.core.tools import tool_registry as R
    import jaeger_ai.main as m
    m._register_builtins(object())
    names = {t.name for t in R.get_tools()}
    assert {"set_autonomy", "get_autonomy"} <= names
