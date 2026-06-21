"""Windowed-app surfaces — headless Qt smoke + full bus round-trip.

Runs offscreen (``QT_QPA_PLATFORM=offscreen``) so it needs no display;
marked ``ui`` so a headless CI can exclude it. The last test proves the
window ↔ AgentBridge chat loop over the chassis bus — the GUI driving the
universal turn logic with no model and no GUI server.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import queue  # noqa: E402
import time  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtWidgets import QApplication  # noqa: E402

from jaeger_os.agent.loop.bridge import AgentBridge  # noqa: E402
from jaeger_os.app.bus.inproc import InProcBus  # noqa: E402
from jaeger_os.core.messages import AgentState, ChatReply  # noqa: E402
from jaeger_os.interfaces.pill.qt import Pill  # noqa: E402
from jaeger_os.interfaces.rich_tui.window import ChatWindow  # noqa: E402
from jaeger_os.interfaces.tray.qt import QtTray  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_window_renders_chat_reply(qapp):
    bus = InProcBus()
    win = ChatWindow(SimpleNamespace(bus=bus, agent_name="Tester", window=None))
    try:
        bus.publish(ChatReply(text="hello from agent"))
        assert _pump(
            qapp, lambda: "hello from agent" in win.rendered_text())
    finally:
        win.teardown()
        bus.close()


def test_window_publishes_chat_message_on_send(qapp):
    bus = InProcBus()
    sent: "queue.Queue[str]" = queue.Queue()
    bus.subscribe("/act/chat", lambda m: sent.put(m.text))
    win = ChatWindow(SimpleNamespace(bus=bus, agent_name="T", window=None))
    try:
        win.input.setText("ping")
        win._send()
        assert sent.get(timeout=2.0) == "ping"
        assert "ping" in win.rendered_text()   # echoed locally
    finally:
        win.teardown()
        bus.close()


def test_agent_state_updates_status(qapp):
    bus = InProcBus()
    win = ChatWindow(SimpleNamespace(bus=bus, agent_name="T", window=None))
    try:
        bus.publish(AgentState(state="thinking"))
        assert _pump(qapp, lambda: "thinking" in win.status.text())
    finally:
        win.teardown()
        bus.close()


def test_tray_constructs_and_closes(qapp):
    bus = InProcBus()
    tray = QtTray(SimpleNamespace(bus=bus, agent_name="T", window=None))
    tray.close()   # must not raise
    bus.close()


def test_window_plus_agent_bridge_full_round_trip(qapp):
    """The real chain: window → ChatMessage → AgentBridge (fake turn) →
    ChatReply → window — no model, no GUI server."""
    bus = InProcBus()
    bridge = AgentBridge(
        bus=bus,
        run_turn=lambda c, t, session_key=None: {"text": f"you said: {t}"},
    )
    bridge.start()

    win = ChatWindow(SimpleNamespace(bus=bus, agent_name="Lilith", window=None))
    try:
        win.input.setText("hi there")
        win._send()
        assert _pump(
            qapp,
            lambda: "you said: hi there" in win.rendered_text())
    finally:
        bridge.stop()
        bridge.join(timeout=2.0)
        win.teardown()
        bus.close()


def test_windowed_manifest_boots_agent_core_over_chassis(qapp, monkeypatch):
    """The ``./launch`` path: JaegerApp(jaeger.windowed.toml) builds the
    Tier-1 ``[core]`` (AgentCore) on the main thread, starts the bridge,
    and a ChatMessage round-trips to a ChatReply over the chassis bus —
    model boot + Qt loop stubbed. Proves host.py folded cleanly into the
    [core] role (one app/host: the chassis)."""
    import pathlib
    import types

    import jaeger_os.main as m
    from jaeger_os.app import JaegerApp
    from jaeger_os.core.messages import MESSAGES, ChatMessage, ChatReply

    cleaned = []
    monkeypatch.setattr(m, "boot_for_tui", lambda **kw: types.SimpleNamespace(
        client=object(), cleanup=lambda: cleaned.append(True)))
    monkeypatch.setattr(
        m, "run_for_voice",
        lambda c, t, session_key="gui": {"text": f"echo: {t}", "error": None})

    repo = pathlib.Path(__file__).resolve().parents[4]
    app = JaegerApp(repo / "jaeger.windowed.toml", registry=MESSAGES)
    assert app.spec.name == "jros-windowed"
    assert app.spec.event_loop == "qt"
    app.boot()   # init_core builds the AgentCore (main thread) + bridge
    try:
        assert app.core is not None
        assert app.core.__class__.__name__ == "AgentCore"
        assert app.core.bridge is not None
        replies = []
        app.bus.subscribe(ChatReply.topic, lambda msg: replies.append(msg.text))
        app.bus.publish(ChatMessage(text="hi core", source="gui"))
        assert _pump(qapp, lambda: replies == ["echo: hi core"])
    finally:
        app.shutdown()
    assert cleaned == [True]   # the core drained + cleaned up the model


def test_pill_submit_invokes_callback(qapp):
    """The Pill is pure UI: submitting clears + hides + hands the text to
    its callback (the tray wires that to the chat window)."""
    got: list[str] = []
    pill = Pill(on_submit=got.append, agent_name="T")
    try:
        pill.input.setText("hi from pill")
        pill._send()
        assert got == ["hi from pill"]
        assert pill.input.text() == ""
        assert not pill.isVisible()
    finally:
        pill.close()


def test_tray_pill_routes_to_chat_window(qapp):
    """Pill submit → tray opens the chat window and renders the user bubble
    there (consistent with a typed message) + publishes ChatMessage once."""
    bus = InProcBus()
    sent: "queue.Queue[str]" = queue.Queue()
    bus.subscribe("/act/chat", lambda m: sent.put(m.text))
    win = ChatWindow(SimpleNamespace(bus=bus, agent_name="T", window=None))
    tray = QtTray(SimpleNamespace(bus=bus, agent_name="T", window=win))
    try:
        tray._submit_from_pill("from the pill")
        assert sent.get(timeout=2.0) == "from the pill"
        assert "from the pill" in win.rendered_text()
    finally:
        tray.close()
        win.teardown()
        bus.close()
