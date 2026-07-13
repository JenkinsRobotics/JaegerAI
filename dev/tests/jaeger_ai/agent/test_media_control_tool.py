"""media_control.py (agent/tools/media_control.py) — 0.9.3 mac-native
suite. All ``osascript`` invocations are mocked — no real Music.app/
Spotify call.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy

# Module and its transport function share a name (``media_control``) —
# the package's ``__init__.py`` does ``from .media_control import
# media_control, now_playing``, which rebinds the package attribute to
# the FUNCTION. ``importlib.import_module`` gets the real submodule so
# ``mc.media_control(...)``/``mc.now_playing(...)`` and ``mc.platform``/
# ``mc.shutil``/``mc.subprocess`` (for patching) both resolve.
mc = importlib.import_module("jaeger_ai.agent.tools.media_control")


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


@pytest.fixture(autouse=True)
def _darwin(monkeypatch):
    monkeypatch.setattr(mc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mc.shutil, "which", lambda name: "/usr/bin/osascript")


def test_targets_music_by_default(monkeypatch):
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args[-1])
        if "Spotify" in args[-1] and "System Events" in args[-1]:
            return _proc(0, stdout="false")
        return _proc(0)

    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    result = mc.media_control("play")
    assert result == {"ok": True, "app": "Music", "action": "play"}
    assert 'tell application "Music" to play' in seen[-1]


def test_targets_spotify_when_running(monkeypatch):
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args[-1])
        if "Spotify" in args[-1] and "System Events" in args[-1]:
            return _proc(0, stdout="true")
        return _proc(0)

    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    result = mc.media_control("pause")
    assert result["app"] == "Spotify"
    assert 'tell application "Spotify" to pause' in seen[-1]


def test_skip_is_alias_for_next(monkeypatch):
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args[-1])
        if "Spotify" in args[-1] and "System Events" in args[-1]:
            return _proc(0, stdout="false")
        return _proc(0)

    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    mc.media_control("skip")
    assert "next track" in seen[-1]


def test_unknown_action_rejected():
    result = mc.media_control("shuffle")
    assert result["ok"] is False
    assert "unknown action" in result["error"]


def test_media_control_osascript_failure(monkeypatch):
    def fake_run(args, **kwargs):
        if "Spotify" in args[-1] and "System Events" in args[-1]:
            return _proc(0, stdout="false")
        return _proc(1, stderr="Music got an error")

    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    result = mc.media_control("play")
    assert result["ok"] is False
    assert "Music got an error" in result["error"]


def test_media_control_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(mc.platform, "system", lambda: "Linux")
    result = mc.media_control("play")
    assert result["ok"] is False
    assert "macOS" in result["error"]


# ── now_playing ───────────────────────────────────────────────────


def test_now_playing_returns_track_info(monkeypatch):
    def fake_run(args, **kwargs):
        if "Spotify" in args[-1] and "System Events" in args[-1]:
            return _proc(0, stdout="false")
        return _proc(0, stdout="Song Name — Artist Name (playing)")

    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    result = mc.now_playing()
    assert result["ok"] is True
    assert result["playing"] is True
    assert "Song Name" in result["now_playing"]


def test_now_playing_nothing_playing(monkeypatch):
    def fake_run(args, **kwargs):
        if "Spotify" in args[-1] and "System Events" in args[-1]:
            return _proc(0, stdout="false")
        return _proc(0, stdout="")

    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    result = mc.now_playing()
    assert result == {"ok": True, "app": "Music", "playing": False, "now_playing": None}


# ── tier + registration ───────────────────────────────────────────


def test_media_control_is_registered_external_effect():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert get_tier(tools["media_control"]) == PermissionTier.EXTERNAL_EFFECT


def test_now_playing_is_registered_read_only():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert get_tier(tools["now_playing"]) == PermissionTier.READ_ONLY
