"""Tray logic — state machine, glyph map, menu generation.

Pure-Python, no GUI imports. The rumps adapter (:mod:`.macos`) calls
into here for every decision it makes:

  - what icon glyph to render → :func:`glyph_for`
  - which menu items, with which enabled flags → :func:`menu_items_for`
  - how to interpret a status snapshot → :class:`TrayModel.update`
  - which callback fires for a menu click → :class:`TrayActions.dispatch`

A future Linux / Windows backend uses the same surface; only the
rendering layer changes.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Callable


# ── state ─────────────────────────────────────────────────────────


class TrayState(enum.Enum):
    """Coarse daemon health visible from the tray.

    Finer-grained agent state (``thinking``, ``running tool``, ...) is
    Phase-2 work — the tray won't show it directly because we'd be
    polling the agent loop every two seconds, which is the wrong
    cadence. That stays on the TUI's status bar."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


# Two presentations:
#
#   1. ``_GLYPHS`` — a one-character text fallback used by hosts that
#      can't render image assets (Linux/Windows trays, headless test
#      runs that just inspect the state→label mapping).
#   2. ``icon_path_for`` — a path to a PNG that rumps loads as the
#      menu-bar icon on macOS. Off-states use a desaturated variant
#      so the user can see the daemon-down state at a glance without
#      a glaring red X. Running uses the full-colour brand mark.
#
# The brand mark is a horizontally mirrored Lilith disc — the L
# silhouette becomes a J. See ``src/jaeger_os/assets/`` and the
# image-generation incantation in
# ``tests/jaeger_os/interfaces/pyside6/tray/test_tray_icons.py``.
_GLYPHS: dict[TrayState, str] = {
    TrayState.STOPPED:  "○",
    TrayState.STARTING: "◐",
    TrayState.RUNNING:  "●",
    TrayState.ERROR:    "⚠",
}


def glyph_for(state: TrayState) -> str:
    """One-character text glyph for the menu-bar slot. Used as a
    fallback by adapters that can't render PNG assets; the macOS
    adapter prefers :func:`icon_path_for` so the user sees the real
    brand mark."""
    return _GLYPHS[state]


# PNG icons shipped alongside the package — see
# ``src/jaeger_os/assets/jaeger_icon{,_off}.png``. The off variant is
# a desaturated version of the colour mark, so the menu-bar slot
# still shows the J shape when the daemon is down — just visibly
# greyed out. We resolve the path lazily so an import on a host
# without the assets dir (a stripped-down install) doesn't error.
def _asset_root():
    """Locate the ``jaeger_os/assets`` directory at runtime."""
    from pathlib import Path
    # Walk up to the jaeger_os package root rather than counting
    # parents — this file moves around (interfaces/pyside6/tray/…)
    # and a hardcoded depth breaks on every relocation.
    for parent in Path(__file__).resolve().parents:
        if parent.name == "jaeger_os":
            return parent / "assets"
    return Path(__file__).resolve().parent / "assets"


# Mapping from state to the icon's asset filename (without the
# directory prefix). The on/off split: ``RUNNING`` uses the colour
# mark; every other state uses the greyed-out variant. The starting
# state could get its own animated icon in a future pass but the
# greyed-out mark + "Jaeger OS: starting…" label is the lower-cost
# version today.
_ICON_NAMES: dict[TrayState, str] = {
    TrayState.STOPPED:  "jaeger_icon_off.png",
    TrayState.STARTING: "jaeger_icon_off.png",
    TrayState.RUNNING:  "jaeger_icon.png",
    TrayState.ERROR:    "jaeger_icon_off.png",
}


def icon_path_for(state: TrayState) -> str | None:
    """Absolute path to the PNG that should fill the menu-bar slot.

    Returns ``None`` when the asset is missing (e.g. a stripped
    install or a host without the assets/ directory) so the caller
    can fall back to :func:`glyph_for`."""
    root = _asset_root()
    name = _ICON_NAMES.get(state)
    if name is None:
        return None
    path = root / name
    if not path.is_file():
        return None
    return str(path)


def asset_path(name: str) -> str | None:
    """Absolute path to ``jaeger_os/assets/<name>``, or None if missing."""
    path = _asset_root() / name
    return str(path) if path.is_file() else None


# ── menu items ────────────────────────────────────────────────────


@dataclass(frozen=True)
class MenuItem:
    """One row in the tray's dropdown.

    ``label`` is the human-visible text. ``action`` is a string key —
    the GUI passes it back to :meth:`TrayActions.dispatch` on click.
    ``action=None`` makes the row a label (no callback). ``enabled``
    controls greyed-out state.

    Separators carry an empty label, no action, and ``enabled=False`` —
    the rumps adapter renders ``MenuItem(label="-")`` as a divider."""
    label: str
    action: str | None = None
    enabled: bool = True


SEPARATOR = MenuItem(label="-", action=None, enabled=False)


def _status_label(state: TrayState) -> MenuItem:
    text = {
        TrayState.STOPPED:  "Jaeger OS: stopped",
        TrayState.STARTING: "Jaeger OS: starting…",
        TrayState.RUNNING:  "Jaeger OS: running",
        TrayState.ERROR:    "Jaeger OS: error — restart needed",
    }[state]
    return MenuItem(label=text, action=None, enabled=False)


def menu_items_for(state: TrayState) -> list[MenuItem]:
    """The menu that should currently be visible. Recomputed on every
    state change; identical-state polls reuse the cached list."""
    running = state is TrayState.RUNNING
    stopped = state is TrayState.STOPPED
    return [
        _status_label(state),
        SEPARATOR,
        MenuItem(label="Start Jaeger OS",   action="start",   enabled=stopped),
        MenuItem(label="Stop Jaeger OS",    action="stop",    enabled=running),
        MenuItem(label="Restart Jaeger OS", action="restart", enabled=running),
        SEPARATOR,
        # 0.2.6: every client launcher lives in this group. Each one
        # is a separate process; the action handler in ``macos.py``
        # spawns the right subprocess and (for terminal-based ones)
        # opens / focuses Terminal.app. Greyed entries are intentional
        # placeholders for surfaces that are landing in a future
        # release — they let operators see what's coming without
        # promising it works today.
        #
        # 'Open Chat (TUI)' is always live: when the daemon is up the
        # handler attaches via ``rich_tui`` (single shared model);
        # otherwise it falls back to the standalone in-process TUI. A
        # PID-file check prevents a second TUI from spawning if one is
        # already up — clicking again just brings that Terminal window
        # to the front.
        MenuItem(label="Open Chat (TUI)",   action="open_tui"),
        # Voice launcher. Spawns ``python -m jaeger_os.plugins.voice_loop``
        # with the active instance pinned. Wake-word required, AEC
        # barge-in when speexdsp is available.
        MenuItem(label="Open Voice",        action="open_voice"),
        # Floating chat window (PyQt6). Disabled placeholder until the
        # GUI lands — see the 0.3.0 / GUI work in dev/docs/.
        MenuItem(label="Open Chat (GUI)",   action="open_gui",
                 enabled=False),
        # Web dashboard — separate future surface (browser-based
        # remote control). Not in active design yet.
        MenuItem(label="Open Web Dashboard", action="open_web",
                 enabled=False),
        SEPARATOR,
        MenuItem(label="About Jaeger OS",  action="about"),
        # "Quit Jaeger OS" tears EVERYTHING down — daemon, every
        # running tray, and the rumps event loop itself. Users
        # expect that picking Quit from the menu kills the whole
        # product, not just the icon. The action handler in
        # ``macos.py`` ties the steps together.
        MenuItem(label="Quit Jaeger OS",     action="quit_tray"),
    ]


# ── model: status snapshot → state ────────────────────────────────


@dataclass
class TrayModel:
    """In-memory view of the daemon's health. The poller feeds
    ``Lifecycle.status()`` dicts in; the GUI reads ``state`` and
    ``last_changed`` to decide whether to redraw."""
    state: TrayState = TrayState.STOPPED
    pid: int | None = None
    reason: str = ""
    last_changed: float = field(default_factory=time.monotonic)

    def update(self, status: dict[str, Any]) -> bool:
        """Apply a status snapshot. Returns ``True`` if the visible
        state actually changed (so the GUI can short-circuit redraws)."""
        new_state = _state_from_status(status)
        new_pid = status.get("pid")
        new_reason = str(status.get("reason") or "")
        if (new_state == self.state
                and new_pid == self.pid
                and new_reason == self.reason):
            return False
        self.state = new_state
        self.pid = new_pid
        self.reason = new_reason
        self.last_changed = time.monotonic()
        return True


def _state_from_status(status: dict[str, Any]) -> TrayState:
    """Map a ``Lifecycle.status()`` dict onto a coarse :class:`TrayState`.

    Note ERROR isn't "exception raised" — it's "daemon is in a state we
    can't usefully act on from a tray click". Today that's just "PID
    alive but socket missing" — the daemon either crashed mid-start or
    is hanging. Either way the user-facing remedy is ``restart``."""
    if status.get("running"):
        return TrayState.RUNNING
    reason = str(status.get("reason") or "").lower()
    if "socket" in reason and status.get("pid") is not None:
        # Process is alive but not serving — wedged.
        return TrayState.ERROR
    # Everything else (no pid, stale pid, garbage pid) is plain off.
    return TrayState.STOPPED


# ── actions ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrayActions:
    """The callbacks the menu can fire. ``dispatch`` is the
    indirection the GUI uses so it doesn't have to bind by identity:
    a menu item carries the action name as a string, the dispatcher
    routes it to the right closure.

    0.2.6: added ``open_voice`` (launches the voice loop) and
    ``open_gui`` (placeholder for the PyQt6 floating chat — landing
    in a later release). Disabled menu items still need a callback
    bound so the dispatcher doesn't crash on a programmer-error
    click on a non-enabled entry; the placeholders are no-ops.
    """
    start: Callable[[], None]
    stop: Callable[[], None]
    restart: Callable[[], None]
    open_tui: Callable[[], None]
    open_voice: Callable[[], None]
    open_gui: Callable[[], None]
    open_web: Callable[[], None]
    quit_tray: Callable[[], None]
    about: Callable[[], None] | None = None

    def dispatch(self, name: str | None) -> None:
        """Fire the named action if known; otherwise silently no-op so
        a click on a status label (action=None) doesn't crash."""
        if name is None:
            return
        handler = {
            "start": self.start,
            "stop": self.stop,
            "restart": self.restart,
            "open_tui": self.open_tui,
            "open_voice": self.open_voice,
            "open_gui": self.open_gui,
            "open_web": self.open_web,
            "quit_tray": self.quit_tray,
            "about": self.about,
        }.get(name)
        if handler is None:
            return
        handler()


__all__ = [
    "MenuItem",
    "SEPARATOR",
    "TrayActions",
    "TrayModel",
    "TrayState",
    "glyph_for",
    "menu_items_for",
]
