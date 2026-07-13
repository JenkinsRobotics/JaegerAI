"""notify.py (agent/tools/notify.py) — 0.9.3 mac-native suite.

``osascript`` invocations are mocked — no real notification is shown.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy

# Module and its one public function share a name (``notify``) — the
# package's ``__init__.py`` does ``from .notify import notify``, which
# rebinds ``jaeger_ai.agent.tools.notify`` to the FUNCTION (last binding
# wins). ``importlib.import_module`` bypasses that attribute shadowing
# and gets the real submodule so ``.platform``/``.shutil``/``.subprocess``
# are patchable.
notify_mod = importlib.import_module("jaeger_ai.agent.tools.notify")


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


def test_notify_success(monkeypatch):
    monkeypatch.setattr(notify_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notify_mod.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args[-1])
        return _proc(0)

    monkeypatch.setattr(notify_mod.subprocess, "run", fake_run)
    result = notify_mod.notify("Reminder", "Stand up and stretch")
    assert result == {"shown": True, "title": "Reminder", "message": "Stand up and stretch"}
    assert "display notification" in seen[-1]
    assert "Stand up and stretch" in seen[-1]
    assert "Reminder" in seen[-1]


def test_notify_escapes_quotes(monkeypatch):
    monkeypatch.setattr(notify_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notify_mod.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = []
    monkeypatch.setattr(notify_mod.subprocess, "run",
                        lambda args, **k: (seen.append(args[-1]), _proc(0))[1])
    notify_mod.notify('Say "hi"', 'It said "hello"')
    assert 'Say \\"hi\\"' in seen[-1]
    assert 'It said \\"hello\\"' in seen[-1]


def test_notify_requires_title_or_message():
    result = notify_mod.notify("", "")
    assert result["shown"] is False
    assert "empty" in result["error"]


def test_notify_failure_reported(monkeypatch):
    monkeypatch.setattr(notify_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notify_mod.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(notify_mod.subprocess, "run", lambda *a, **k: _proc(1, stderr="boom"))
    result = notify_mod.notify("T", "M")
    assert result["shown"] is False
    assert "boom" in result["error"]


def test_notify_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(notify_mod.platform, "system", lambda: "Linux")
    result = notify_mod.notify("T", "M")
    assert result["shown"] is False
    assert "macOS" in result["error"]


def test_notify_is_registered_write_local():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert get_tier(tools["notify"]) == PermissionTier.WRITE_LOCAL
