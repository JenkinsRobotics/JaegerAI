"""clipboard.py (agent/tools/clipboard.py) — 0.9.3 mac-native suite.

``pbpaste``/``pbcopy`` invocations are mocked — no real clipboard touch.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.agent.tools import clipboard
from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


def test_clipboard_read_success(monkeypatch):
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/pbpaste")
    monkeypatch.setattr(clipboard.subprocess, "run", lambda *a, **k: _proc(0, stdout="hello"))

    result = clipboard.clipboard_read()
    assert result == {"read": True, "text": "hello"}


def test_clipboard_read_missing_binary_actionable(monkeypatch):
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)
    result = clipboard.clipboard_read()
    assert result["read"] is False
    assert "pbpaste" in result["error"]


def test_clipboard_read_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Linux")
    result = clipboard.clipboard_read()
    assert result["read"] is False
    assert "macOS" in result["error"]


def test_clipboard_write_success(monkeypatch):
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/pbcopy")
    seen = {}

    def fake_run(args, **kwargs):
        seen["input"] = kwargs.get("input")
        return _proc(0)

    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    result = clipboard.clipboard_write("copy me")
    assert result == {"written": True, "bytes": len(b"copy me")}
    assert seen["input"] == "copy me"


def test_clipboard_write_failure_reported(monkeypatch):
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/pbcopy")
    monkeypatch.setattr(clipboard.subprocess, "run", lambda *a, **k: _proc(1, stderr="denied"))
    result = clipboard.clipboard_write("x")
    assert result["written"] is False
    assert "denied" in result["error"]


def test_clipboard_write_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(clipboard.platform, "system", lambda: "Linux")
    result = clipboard.clipboard_write("x")
    assert result["written"] is False
    assert "macOS" in result["error"]


def test_clipboard_read_is_registered_read_only():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert get_tier(tools["clipboard_read"]) == PermissionTier.READ_ONLY


def test_clipboard_write_is_registered_write_local():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert get_tier(tools["clipboard_write"]) == PermissionTier.WRITE_LOCAL
