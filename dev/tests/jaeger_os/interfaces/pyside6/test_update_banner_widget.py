"""UpdateBanner — the reusable "update available" widget. Offscreen (conftest
defaults QT_QPA_PLATFORM=offscreen). The GitHub check + the QProcess update run
are not exercised here (run_default=False so clicking never spawns); we assert
the reveal logic + the click contract."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _banner():
    from jaeger_os.interfaces.pyside6.widgets.update_banner import UpdateBanner
    # auto_start=False → no network; run_default=False → click won't spawn update
    return UpdateBanner(auto_start=False, run_default=False)


def test_hidden_until_update_available(_app):
    b = _banner()
    assert b.isHidden()
    b.set_status({"available": False, "latest": None, "current": "0.5.2"})
    assert b.isHidden()
    b.set_status(None)                                  # offline probe
    assert b.isHidden()
    b.set_status({"available": True, "latest": "9.9.9", "current": "0.5.2"})
    assert not b.isHidden()
    assert "9.9.9" in b._label.text()


def test_click_emits_target_without_running(_app):
    b = _banner()
    b.set_status({"available": True, "latest": "9.9.9", "current": "0.5.2"})
    seen = []
    b.updateRequested.connect(seen.append)
    b._btn.click()                                       # run_default=False → no dialog
    assert seen == ["9.9.9"]
