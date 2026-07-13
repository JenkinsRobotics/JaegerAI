"""system_control.py (agent/tools/system_control.py) — 0.9.3 mac-native
suite. All ``osascript``/``defaults``/``caffeinate`` invocations are
mocked — no real system setting is ever touched.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy

# Module and its dispatch function share a name (``system_control``) —
# the package's ``__init__.py`` does ``from .system_control import
# system_control``, which rebinds the package attribute to the
# FUNCTION. ``importlib.import_module`` gets the real submodule so
# ``sc.system_control(...)`` (the function) and ``sc.platform`` /
# ``sc.shutil`` / ``sc.subprocess`` (for patching) both resolve.
sc = importlib.import_module("jaeger_ai.agent.tools.system_control")


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


@pytest.fixture(autouse=True)
def _darwin(monkeypatch):
    monkeypatch.setattr(sc.platform, "system", lambda: "Darwin")


# ── volume ────────────────────────────────────────────────────────


def test_volume_sets_and_clamps(monkeypatch):
    seen = []
    monkeypatch.setattr(sc.subprocess, "run",
                        lambda args, **k: (seen.append(args[-1]), _proc(0))[1])
    result = sc.system_control("volume", 150)
    assert result == {"changed": True, "action": "volume", "value": 100}
    assert "set volume output volume 100" in seen[-1]


def test_volume_negative_clamps_to_zero(monkeypatch):
    monkeypatch.setattr(sc.subprocess, "run", lambda *a, **k: _proc(0))
    result = sc.system_control("volume", -10)
    assert result["value"] == 0


def test_volume_failure_reported(monkeypatch):
    monkeypatch.setattr(sc.subprocess, "run", lambda *a, **k: _proc(1, stderr="denied"))
    result = sc.system_control("volume", 50)
    assert result["changed"] is False
    assert "denied" in result["error"]


# ── brightness ────────────────────────────────────────────────────


def test_brightness_missing_cli_is_actionable(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda name: None)
    result = sc.system_control("brightness", 50)
    assert result["changed"] is False
    assert "brew install brightness" in result["error"]


def test_brightness_success(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/opt/homebrew/bin/brightness")
    seen = []
    monkeypatch.setattr(sc.subprocess, "run",
                        lambda args, **k: (seen.append(args), _proc(0))[1])
    result = sc.system_control("brightness", 80)
    assert result["changed"] is True
    assert seen[0][0] == "/opt/homebrew/bin/brightness"
    assert seen[0][1] == "0.8"


# ── dark_mode ─────────────────────────────────────────────────────


def test_dark_mode_on(monkeypatch):
    seen = []
    monkeypatch.setattr(sc.subprocess, "run",
                        lambda args, **k: (seen.append(args[-1]), _proc(0))[1])
    result = sc.system_control("dark_mode", "on")
    assert result == {"changed": True, "action": "dark_mode", "value": True}
    assert "set dark mode to true" in seen[-1]


def test_dark_mode_off(monkeypatch):
    seen = []
    monkeypatch.setattr(sc.subprocess, "run",
                        lambda args, **k: (seen.append(args[-1]), _proc(0))[1])
    sc.system_control("dark_mode", "off")
    assert "set dark mode to false" in seen[-1]


# ── do_not_disturb ────────────────────────────────────────────────


def test_do_not_disturb_on_writes_pref_and_restarts_center(monkeypatch):
    calls = []
    monkeypatch.setattr(sc.subprocess, "run",
                        lambda args, **k: (calls.append(args), _proc(0))[1])
    result = sc.system_control("do_not_disturb", "on")
    assert result["changed"] is True
    assert calls[0][:4] == ["defaults", "-currentHost", "write", "com.apple.notificationcenterui"]
    assert calls[1] == ["killall", "NotificationCenter"]
    assert "Sonoma" in result["note"]


def test_do_not_disturb_pref_write_failure_reported(monkeypatch):
    monkeypatch.setattr(sc.subprocess, "run", lambda *a, **k: _proc(1, stderr="nope"))
    result = sc.system_control("do_not_disturb", "off")
    assert result["changed"] is False
    assert "nope" in result["error"]


# ── prevent_sleep ─────────────────────────────────────────────────


def test_prevent_sleep_starts_detached_caffeinate(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/usr/bin/caffeinate")
    seen = {}

    class FakeProc:
        pid = 4242

    def fake_popen(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(sc.subprocess, "Popen", fake_popen)
    result = sc.system_control("prevent_sleep", 5)
    assert result == {"changed": True, "action": "prevent_sleep", "minutes": 5, "pid": 4242,
                       "note": "auto-expires after the given minutes — no stop call needed"}
    assert seen["args"] == ["caffeinate", "-i", "-t", "300"]
    assert seen["kwargs"].get("start_new_session") is True


def test_prevent_sleep_invalid_minutes():
    result = sc.system_control("prevent_sleep", "not-a-number")
    assert result["changed"] is False
    assert "invalid minutes" in result["error"]


def test_prevent_sleep_missing_caffeinate(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda name: None)
    result = sc.system_control("prevent_sleep", 10)
    assert result["changed"] is False
    assert "caffeinate" in result["error"]


# ── dispatch + platform guard ────────────────────────────────────


def test_unknown_action_rejected():
    result = sc.system_control("teleport")
    assert result["changed"] is False
    assert "unknown action" in result["error"]


def test_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(sc.platform, "system", lambda: "Linux")
    result = sc.system_control("volume", 50)
    assert result["changed"] is False
    assert "macOS" in result["error"]


def test_system_control_is_registered_external_effect():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert get_tier(tools["system_control"]) == PermissionTier.EXTERNAL_EFFECT
