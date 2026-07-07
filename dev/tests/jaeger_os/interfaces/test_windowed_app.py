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

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from jaeger_os.agent.loop.bridge import AgentBridge  # noqa: E402
from jaeger_os.transport import InProcBus  # noqa: E402
from jaeger_os.core.messages import AgentState, ChatReply  # noqa: E402
from jaeger_os.interfaces.pyside6.pill.qt import Pill  # noqa: E402
from jaeger_os.interfaces.pyside6.rich_tui.window import ChatWindow  # noqa: E402
from jaeger_os.interfaces.pyside6.tray.qt import QtTray  # noqa: E402


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
    from jaeger_os.core.messages import ChatMessage, ChatReply

    cleaned = []
    monkeypatch.setattr(m, "boot_for_tui", lambda **kw: types.SimpleNamespace(
        client=object(), cleanup=lambda: cleaned.append(True)))
    monkeypatch.setattr(
        m, "run_for_voice",
        lambda c, t, session_key="gui": {"text": f"echo: {t}", "error": None})

    repo = pathlib.Path(__file__).resolve().parents[4]
    app = JaegerApp(repo / "jaeger.windowed.toml")
    assert app.spec.name == "jros-windowed"
    assert app.spec.event_loop == "qt"
    app.boot()   # init_core builds the AgentCore (main thread) + bridge
    try:
        assert isinstance(app.bus, InProcBus)   # 0.8 U1: chassis on transport.InProcBus
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


def test_pill_is_the_faithful_two_row_card(qapp):
    """The Pill mirrors the Lilith ``PillWindow`` / Claude quick-input: an
    input row (glyph + field + New Chat ▾ + send) over a callout row
    (share blurb + action chips). This was stripped to one row once
    before — pin the structure so it can't silently regress again."""
    from PySide6.QtWidgets import QFrame, QLabel, QPushButton

    pill = Pill(on_submit=lambda _t: None, agent_name="Jaeger",
                on_open_chat=lambda: None)
    try:
        buttons = {b.text() for b in pill.findChildren(QPushButton)}
        labels = {l.text() for l in pill.findChildren(QLabel)}
        dividers = [f for f in pill.findChildren(QFrame)
                    if f.objectName() == "PillDivider"]
        assert {"New Chat ▾", "↑", "Turn on screenshots", "Not now"} <= buttons
        assert "Quickly share content with Jaeger" in labels
        assert "Needs additional permission" in labels
        assert len(dividers) == 1
        assert (pill.width(), pill.height()) == (720, 140)
    finally:
        pill.close()


def test_chat_renders_markdown_not_literal_asterisks(qapp):
    """The agent replies in Markdown; the window must render it (bold,
    lists, code) — never leak literal ``**asterisks**`` into the
    transcript. Regression for the raw-markdown bug."""
    bus = InProcBus()
    win = ChatWindow(SimpleNamespace(bus=bus, agent_name="jarvis", window=None))
    try:
        win._append_turn(
            "assistant",
            "**Core Capabilities**\n\n* **Memory:** remember\n* read/write\n\n"
            "Use `code` and *italics*.")
        shown = win.transcript.toPlainText()
        assert "**" not in shown          # markers consumed, not printed
        assert "`code`" not in shown      # inline code unwrapped
        assert "Core Capabilities" in shown and "Memory:" in shown
        # CLI-style turn markers present.
        win._append_turn("user", "hi")
        assert "●" in win.transcript.toPlainText()  # user bullet
    finally:
        win.teardown()


def test_chat_session_routing_and_slash_commands(qapp):
    """One app-agent, many windows: each window renders only its own
    session's replies, and ``/new`` starts a fresh conversation."""
    from jaeger_os.core.messages import ChatReply

    win = ChatWindow(SimpleNamespace(bus=InProcBus(), agent_name="jarvis",
                                     window=None))
    try:
        sid = win._session
        # A reply tagged for another window's session is ignored.
        win._on_msg(ChatReply(text="other-window", session="ZZZZ"))
        win._on_msg(ChatReply(text="mine", session=sid))
        shown = win.transcript.toPlainText()
        assert "other-window" not in shown and "mine" in shown
        # /new → new session id + cleared transcript/history.
        win.input.setText("/new"); win._send()
        assert win._session != sid and win._messages == []
        # /help lists commands; unknown is reported.
        win.input.setText("/help"); win._send()
        assert "new conversation" in win.transcript.toPlainText()
        win.input.setText("/bogus"); win._send()
        assert "unknown command" in win.transcript.toPlainText()
    finally:
        win.teardown()


def test_agent_tool_events_reach_the_bus(qapp):
    """The agent loop's ``tool.progress`` hook → chassis ``ToolEvent`` via
    the bridge adapter (the seam that lights up 'see tool use')."""
    from jaeger_os.agent.loop.bridge import _BusEventAdapter
    from jaeger_os.core.messages import ToolEvent

    bus = InProcBus()
    seen: "queue.Queue" = queue.Queue()
    bus.subscribe(ToolEvent.topic, seen.put)
    adapter = _BusEventAdapter(bus)
    adapter.publish("tool.progress", name="web_search", phase="start")
    adapter.publish("tool.progress", name="web_search", phase="done",
                    elapsed_s=1.2)
    a = seen.get(timeout=2.0)
    b = seen.get(timeout=2.0)
    assert (a.name, a.phase) == ("web_search", "start")
    assert b.phase == "done" and abs(b.elapsed_s - 1.2) < 0.01


def test_chat_renders_live_tool_activity(qapp):
    """``ToolEvent`` start → status line; done → a ``⏵`` activity line with
    elapsed (the windowed echo of the TUI's ``┊`` tool lines)."""
    from jaeger_os.core.messages import ToolEvent

    win = ChatWindow(SimpleNamespace(bus=InProcBus(), agent_name="jarvis",
                                     window=None))
    try:
        win._on_msg(ToolEvent(name="web_search", phase="start"))
        assert "running web_search" in win.status.text()
        win._on_msg(ToolEvent(name="web_search", phase="done", elapsed_s=1.2))
        shown = win.transcript.toPlainText()
        assert "web_search" in shown and "1.2s" in shown
    finally:
        win.teardown()


def test_tray_dropdown_status_labels(qapp):
    """The dropdown's status row speaks the operator's words: idle is
    'Standing by', thinking is 'In deep thought…'. Pins the mapping."""
    from jaeger_os.interfaces.pyside6.tray.menu import TrayMenu

    menu = TrayMenu(agent_name="Jaeger",
                    on_quick_input=lambda: None, on_open_chat=lambda: None,
                    on_quit=lambda: None)
    try:
        menu.set_state("idle")
        assert menu._state_label.text() == "Standing by"
        menu.set_state("thinking")
        assert menu._state_label.text() == "In deep thought…"
        menu.set_state("error")
        assert "wrong" in menu._state_label.text().lower()
    finally:
        menu.close()


def test_tray_dropdown_closes_when_clicking_another_qt_window(qapp):
    """Click-away must include other in-process JROS windows, not just
    unrelated macOS apps."""
    from jaeger_os.interfaces.pyside6.tray.menu import TrayMenu

    menu = TrayMenu(agent_name="Jaeger",
                    on_quick_input=lambda: None, on_open_chat=lambda: None,
                    on_quit=lambda: None)
    other = QWidget()
    try:
        menu.show()
        menu._can_dismiss = True
        menu._install_click_filter()
        other.setGeometry(menu.x() + menu.width() + 40, menu.y() + 40, 120, 80)
        other.show()
        qapp.processEvents()

        local = QPoint(10, 10)
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(local),
            QPointF(other.mapToGlobal(local)),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(other, event)
        qapp.processEvents()

        assert not menu.isVisible()
    finally:
        menu.close()
        other.close()


def test_tray_tracks_live_agent_state(qapp):
    """``/sense/agent_state`` drives the tray's status — the slot the bus
    bridge fires. Drive it directly (deterministic, no delivery thread)."""
    from jaeger_os.interfaces.pyside6.tray.qt import QtTray

    tray = QtTray(SimpleNamespace(bus=None, window=None,
                                  core=SimpleNamespace(agent_name="J",
                                                       model_name="m")))
    try:
        assert tray._state == "idle"
        tray._on_state(SimpleNamespace(state="thinking"))
        assert tray._state == "thinking"
    finally:
        tray.close()


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
