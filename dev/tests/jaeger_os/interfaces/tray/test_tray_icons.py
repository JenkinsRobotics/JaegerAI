"""Tray menu-bar icon resolution.

The macOS rumps adapter fills the menu-bar slot with a PNG —
``jaeger_icon.png`` when the daemon is running, the desaturated
``jaeger_icon_off.png`` otherwise — instead of the one-character
text glyph. This file pins the contract:

  * the assets exist and resolve to a real file on disk
  * RUNNING gets the colour variant; every other state gets the
    desaturated one (so the J shape stays visible but reads as
    "off" without a glaring red X)
  * the resolver falls back gracefully when the asset is missing
    (stripped install / non-macOS host)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_os.interfaces.pyside6.tray.base import (
    TrayState,
    icon_path_for,
    glyph_for,
)


def test_assets_are_bundled_with_the_package():
    """The PNGs ship under ``jaeger_os/assets``. A wheel that drops
    them would degrade the tray to text fallback silently — this
    test catches it."""
    from jaeger_os.interfaces.pyside6.tray.base import _asset_root
    root = _asset_root()
    assert (root / "jaeger_icon.png").is_file()
    assert (root / "jaeger_icon_off.png").is_file()


def test_running_state_resolves_to_the_colour_mark():
    """RUNNING — the colour brand mark. That's the user's "Jaeger
    is alive" signal in the menu bar."""
    path = icon_path_for(TrayState.RUNNING)
    assert path is not None
    assert Path(path).name == "jaeger_icon.png"


@pytest.mark.parametrize("state", [
    TrayState.STOPPED,
    TrayState.STARTING,
    TrayState.ERROR,
])
def test_off_states_resolve_to_the_desaturated_mark(state):
    """STOPPED / STARTING / ERROR — desaturated variant. We still
    show the J silhouette (so the menu-bar slot keeps its identity)
    but desaturated so the user reads it as 'not running'."""
    path = icon_path_for(state)
    assert path is not None
    assert Path(path).name == "jaeger_icon_off.png"


def test_resolver_returns_none_when_asset_is_missing(monkeypatch, tmp_path):
    """If the assets/ dir isn't on disk (a stripped install or a
    test environment), the resolver returns None so the adapter
    falls back to the text glyph. The rumps adapter checks for None
    and uses ``glyph_for`` in that case."""
    from jaeger_os.interfaces.pyside6.tray import base as tray_base
    monkeypatch.setattr(tray_base, "_asset_root", lambda: tmp_path)
    # tmp_path has no PNGs in it.
    assert icon_path_for(TrayState.RUNNING) is None
    # Glyph fallback still works regardless.
    assert glyph_for(TrayState.RUNNING) == "●"
