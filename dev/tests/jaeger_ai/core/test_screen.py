"""Live screen capture + OCR — no real screencapture / Vision call."""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime import screen
from jaeger_os.core.safety.permissions import (
    AllowAllProvider,
    PermissionPolicy,
    use_policy,
)
from jaeger_os.core.tools.tool_registry import get_tools


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


def test_see_screen_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(screen.platform, "system", lambda: "Linux")
    result = screen.see_screen()
    assert result["ok"] is False
    assert "macOS" in result["error"]


def test_unknown_target_is_refused(monkeypatch):
    monkeypatch.setattr(screen.platform, "system", lambda: "Darwin")
    result = screen.see_screen(target="region")
    assert result["ok"] is False
    assert "unknown target" in result["error"]


def test_capture_then_ocr_on_success(monkeypatch, tmp_path):
    dest = tmp_path / "screen_latest.png"
    dest.write_bytes(b"PNG")
    monkeypatch.setattr(screen.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(screen, "_capture_path", lambda: dest)
    monkeypatch.setattr(screen, "_frontmost_window_id", lambda: None)

    def _fake_capture(path, *, window_id=None):
        assert path == dest
        assert window_id is None
        return {"ok": True, "path": str(dest)}

    monkeypatch.setattr(screen, "_run_screencapture", _fake_capture)

    def _ocr(path):
        assert path == str(dest)
        return {"ok": True, "text": "Inbox 12 unread", "page_count": 1}

    import types
    import sys

    fake_ocr = types.ModuleType("jaeger_agent.tools.ocr")
    fake_ocr.ocr_file = _ocr
    monkeypatch.setitem(sys.modules, "jaeger_agent.tools.ocr", fake_ocr)

    result = screen.see_screen(target="screen")
    assert result["ok"] is True
    assert result["captured"] is True
    assert result["ocr_ok"] is True
    assert result["text"] == "Inbox 12 unread"
    assert result["path"] == str(dest)


def test_ocr_failure_still_returns_the_screenshot(monkeypatch, tmp_path):
    dest = tmp_path / "screen_latest.png"
    dest.write_bytes(b"PNG")
    monkeypatch.setattr(screen.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(screen, "_capture_path", lambda: dest)
    monkeypatch.setattr(
        screen, "_run_screencapture",
        lambda path, *, window_id=None: {"ok": True, "path": str(path)},
    )
    import types
    import sys

    fake_ocr = types.ModuleType("jaeger_agent.tools.ocr")
    fake_ocr.ocr_file = lambda path: {
        "ok": False, "available": False, "error": "Vision missing",
    }
    monkeypatch.setitem(sys.modules, "jaeger_agent.tools.ocr", fake_ocr)

    result = screen.see_screen()
    assert result["ok"] is True
    assert result["captured"] is True
    assert result["ocr_ok"] is False
    assert result["ocr_available"] is False
    assert result["path"] == str(dest)


def test_window_falls_back_to_display_without_an_id(monkeypatch, tmp_path):
    dest = tmp_path / "screen_latest.png"
    dest.write_bytes(b"PNG")
    monkeypatch.setattr(screen.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(screen, "_capture_path", lambda: dest)
    monkeypatch.setattr(screen, "_frontmost_window_id", lambda: None)
    seen = {}

    def _cap(path, *, window_id=None):
        seen["window_id"] = window_id
        return {"ok": True, "path": str(path)}

    monkeypatch.setattr(screen, "_run_screencapture", _cap)
    import types
    import sys

    fake_ocr = types.ModuleType("jaeger_agent.tools.ocr")
    fake_ocr.ocr_file = lambda path: {"ok": True, "text": "x", "page_count": 1}
    monkeypatch.setitem(sys.modules, "jaeger_agent.tools.ocr", fake_ocr)

    result = screen.see_screen(target="window")
    assert result["ok"] is True
    assert seen["window_id"] is None
    assert "frontmost window" in result.get("note", "")


def test_screencapture_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(screen.shutil, "which", lambda name: None)
    dest = tmp_path / "x.png"
    out = screen._run_screencapture(dest)
    assert out["ok"] is False
    assert "screencapture" in out["error"]


def test_denied_tcc_has_a_grant_reminder(monkeypatch, tmp_path):
    dest = tmp_path / "x.png"
    monkeypatch.setattr(screen.shutil, "which", lambda name: "/usr/sbin/screencapture")
    monkeypatch.setattr(screen, "_screen_recording_granted", lambda: False)

    class _Proc:
        returncode = 1
        stderr = b"could not create image"

    monkeypatch.setattr(
        screen.subprocess, "run",
        lambda *a, **k: _Proc(),
    )
    out = screen._run_screencapture(dest)
    assert out["ok"] is False
    assert "Screen Recording" in out["error"]
    assert out["tcc"] == "screen_recording"


def test_tools_are_registered_read_only():
    tools = {t.name: t for t in get_tools()}
    assert "see_screen" in tools
    assert "ocr_window" in tools
    assert tools["see_screen"].side_effect == "read"
    assert tools["ocr_window"].side_effect == "read"
