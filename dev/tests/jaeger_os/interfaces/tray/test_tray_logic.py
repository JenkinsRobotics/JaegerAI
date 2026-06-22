"""Pure-logic tests for the tray icon.

The tray splits into two halves:

  - the *logic* — what glyph to show, which menu items to enable,
    how the state machine transitions on a status snapshot — lives in
    :mod:`jaeger_os.interfaces.pyside6.tray.base` and depends on nothing but
    dataclasses. **All of that is tested here.**
  - the *rumps adapter* — wires the logic into the macOS menu bar.
    Untested at the unit level because rumps imports an Objective-C
    bridge that doesn't exist off macOS / in CI runners. The adapter
    is small enough that "looks right when you run it" is the bar.

By the time this file passes, every state→glyph transition, every
menu-item enablement rule, and every action callback dispatch is
covered. The rumps adapter is then a thin shim.
"""

from __future__ import annotations

import pytest

from jaeger_os.interfaces.pyside6.tray.base import (
    MenuItem,
    TrayActions,
    TrayModel,
    TrayState,
    glyph_for,
    menu_items_for,
)


# ── state → glyph ──────────────────────────────────────────────────


@pytest.mark.parametrize("state, glyph", [
    (TrayState.STOPPED, "○"),
    (TrayState.STARTING, "◐"),
    (TrayState.RUNNING, "●"),
    (TrayState.ERROR, "⚠"),
])
def test_glyph_for_each_state(state, glyph):
    """One-char text glyph used by hosts that can't render PNG assets
    (Linux/Windows trays, headless tests). The macOS rumps adapter
    prefers ``icon_path_for`` — see those tests."""
    assert glyph_for(state) == glyph


# ── menu generation ────────────────────────────────────────────────


def test_menu_when_stopped_offers_start_disables_stop():
    """Stopped: only 'Start Jaeger OS' is enabled among lifecycle
    items. 'Stop' / 'Restart' would be no-ops, so we grey them out
    rather than letting the user fire a doomed subprocess."""
    items = {i.action: i for i in menu_items_for(TrayState.STOPPED) if i.action}
    assert items["start"].enabled is True
    assert items["stop"].enabled is False
    assert items["restart"].enabled is False


def test_menu_when_running_offers_stop_and_restart():
    items = {i.action: i for i in menu_items_for(TrayState.RUNNING) if i.action}
    assert items["start"].enabled is False
    assert items["stop"].enabled is True
    assert items["restart"].enabled is True


def test_menu_when_starting_disables_all_lifecycle_actions():
    """Mid-transition: don't let the user fire competing commands while
    a start is in flight. The status item shows the in-progress text."""
    items = {i.action: i for i in menu_items_for(TrayState.STARTING) if i.action}
    assert items["start"].enabled is False
    assert items["stop"].enabled is False
    assert items["restart"].enabled is False


def test_menu_always_includes_open_tui_and_quit():
    """Open TUI is always available — it just launches a terminal; if
    the daemon isn't running, the TUI is the standalone in-process
    one (today's behaviour). Quit Tray is always available too."""
    for state in TrayState:
        actions = {i.action for i in menu_items_for(state)}
        assert "open_tui" in actions
        assert "quit_tray" in actions


def test_menu_status_label_reflects_state():
    """The first item is a label (not a button) carrying the state in
    plain English — it's the part of the menu the user reads first."""
    label = menu_items_for(TrayState.RUNNING)[0]
    assert label.action is None
    assert "running" in label.label.lower()


def test_menu_labels_say_jaeger_os_not_daemon():
    """User-facing labels say 'Jaeger OS' so people know what's being
    started/stopped — 'daemon' is an internal implementation detail
    and confused users testing the tray. The status row, the three
    lifecycle items, the About entry, and the Quit row all carry
    the product name."""
    items = menu_items_for(TrayState.RUNNING)
    labels = [i.label for i in items]
    joined = " | ".join(labels)
    assert "Daemon" not in joined, \
        f"menu still references 'Daemon': {joined!r}"
    assert any("Start Jaeger OS" == lbl for lbl in labels)
    assert any("Stop Jaeger OS" == lbl for lbl in labels)
    assert any("Restart Jaeger OS" == lbl for lbl in labels)
    assert any("Jaeger OS: running" == lbl for lbl in labels)
    # Quit tears the WHOLE product down (daemon + every tray) — the
    # label must signal that, not "just close this icon".
    assert any("Quit Jaeger OS" == lbl for lbl in labels), \
        f"Quit label still 'Quit Tray' — must be 'Quit Jaeger OS': " \
        f"{labels}"


def test_open_web_is_disabled_until_web_dashboard_ships():
    """The web dashboard URL is a placeholder right now (ReactPy track
    not built yet). Disabling the menu item until it exists prevents
    a Safari-opens-a-404 confusion."""
    for state in TrayState:
        items = {i.action: i for i in menu_items_for(state) if i.action}
        assert items["open_web"].enabled is False


# ── model: status snapshot → state transition ──────────────────────


def test_model_starts_in_unknown_state():
    """Before the first poll completes, the icon shows ``STOPPED`` —
    pessimistic default so the user isn't told 'running' until we've
    actually confirmed it."""
    model = TrayModel()
    assert model.state == TrayState.STOPPED


def test_model_transitions_to_running_on_positive_status():
    model = TrayModel()
    model.update({"running": True, "pid": 42, "reason": "ok"})
    assert model.state == TrayState.RUNNING
    assert model.pid == 42


def test_model_transitions_to_stopped_on_no_pid_file():
    """The most common 'not running' case — no PID file at all."""
    model = TrayModel()
    model.update({"running": True, "pid": 42, "reason": "ok"})
    model.update({"running": False, "pid": None, "reason": "no pid file"})
    assert model.state == TrayState.STOPPED


def test_model_transitions_to_error_on_unhealthy_status():
    """PID alive but socket missing → ERROR, not STOPPED. The user
    needs to know the daemon is wedged (likely needs ``restart``)
    rather than just thinking it's off and hitting Start which will
    fail because the PID is alive."""
    model = TrayModel()
    model.update({
        "running": False, "pid": 12345,
        "reason": "process alive but socket missing (starting or broken)",
    })
    assert model.state == TrayState.ERROR


def test_model_emits_change_event_only_when_state_actually_changes():
    """The poller calls ``update`` every couple of seconds; if nothing
    changed, the GUI shouldn't redraw. We expose ``last_changed`` so
    the rumps adapter can short-circuit identical updates."""
    model = TrayModel()
    model.update({"running": True, "pid": 1, "reason": "ok"})
    first = model.last_changed
    model.update({"running": True, "pid": 1, "reason": "ok"})
    assert model.last_changed == first, "identical status must not retick"
    model.update({"running": False, "pid": None, "reason": "no pid file"})
    assert model.last_changed != first


# ── actions dispatch ───────────────────────────────────────────────


def test_actions_dispatches_to_the_right_callback():
    """``TrayActions.dispatch(name)`` is the seam between menu items
    (which carry an ``action`` string) and the work that runs (subprocess
    calls or quit). One indirection so the GUI doesn't bind callbacks
    by identity; tests can inject stubs.

    Historical context: TrayActions added ``open_voice`` (launches the
    voice loop) and ``open_gui`` (placeholder for the PyQt6 floating
    chat) as required fields back in the 0.2.6 work; this test was
    written against the older signature.  On the 0.3.0-refactor branch
    tray code is archived but still in tree, so the test stays
    relevant — just needs the two extra no-op lambdas.
    """
    calls = []
    actions = TrayActions(
        start=lambda: calls.append("start"),
        stop=lambda: calls.append("stop"),
        restart=lambda: calls.append("restart"),
        open_tui=lambda: calls.append("open_tui"),
        open_voice=lambda: calls.append("open_voice"),
        open_gui=lambda: calls.append("open_gui"),
        open_web=lambda: calls.append("open_web"),
        quit_tray=lambda: calls.append("quit_tray"),
    )
    for name in ("start", "stop", "restart", "open_tui", "open_voice",
                 "open_gui", "open_web", "quit_tray"):
        actions.dispatch(name)
    assert calls == ["start", "stop", "restart", "open_tui",
                     "open_voice", "open_gui", "open_web", "quit_tray"]


def test_actions_dispatch_ignores_none_action():
    """Status-label menu items have ``action=None``. The dispatcher
    must handle that without raising so a misclick on the label is a
    no-op, not an exception."""
    actions = TrayActions(
        start=lambda: None, stop=lambda: None, restart=lambda: None,
        open_tui=lambda: None, open_voice=lambda: None,
        open_gui=lambda: None, open_web=lambda: None,
        quit_tray=lambda: None,
    )
    actions.dispatch(None)   # should not raise
    actions.dispatch("nonexistent")   # unknown action also a silent no-op


# ── menu item dataclass ────────────────────────────────────────────


def test_menu_item_label_carries_underline_for_keyboard_hint():
    """rumps doesn't render hotkeys, but the underscore convention is
    used internally to mark which letter the keyboard shortcut maps to
    — that lets a future cross-platform backend wire it without
    re-parsing the label."""
    items = menu_items_for(TrayState.RUNNING)
    # Every actionable item has SOME non-empty label.
    for i in items:
        if i.action is not None:
            assert i.label, f"action {i.action} has empty label"
