"""shortcuts.py (agent/tools/shortcuts.py) — 0.9.3 mac-native suite.

``shortcuts`` CLI invocations are mocked here — no real automation runs,
no real subprocess. Modeled on test_email_tool.py's shape (tier gate
tested separately from backend logic).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.agent.tools import shortcuts
from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


# ── list_shortcuts ─────────────────────────────────────────────────


def test_list_shortcuts_returns_names(monkeypatch):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(args, **kwargs):
        assert args == ["shortcuts", "list"]
        return _proc(0, stdout="Morning Routine\nBackup Photos\n")

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    result = shortcuts.list_shortcuts()
    assert result == {"listed": True, "shortcuts": ["Morning Routine", "Backup Photos"], "count": 2}


def test_list_shortcuts_empty_is_a_friendly_note(monkeypatch):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: "/usr/bin/shortcuts")
    monkeypatch.setattr(shortcuts.subprocess, "run", lambda *a, **k: _proc(0, stdout=""))

    result = shortcuts.list_shortcuts()
    assert result["listed"] is True
    assert result["shortcuts"] == []
    assert "no shortcuts installed" in result["note"]


def test_list_shortcuts_cli_missing_is_actionable(monkeypatch):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: None)

    result = shortcuts.list_shortcuts()
    assert result["listed"] is False
    assert "shortcuts` CLI is not on PATH" in result["error"] or "not on PATH" in result["error"]


def test_list_shortcuts_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Linux")
    result = shortcuts.list_shortcuts()
    assert result["listed"] is False
    assert "macOS" in result["error"]


# ── run_shortcut ──────────────────────────────────────────────────


def test_run_shortcut_success_no_input(monkeypatch, tmp_path):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: "/usr/bin/shortcuts")

    def fake_run(args, **kwargs):
        assert args[:3] == ["shortcuts", "run", "Morning Routine"]
        assert "-i" not in args  # no input given
        out_idx = args.index("-o") + 1
        from pathlib import Path
        Path(args[out_idx]).write_text("done", encoding="utf-8")
        return _proc(0)

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    result = shortcuts.run_shortcut("Morning Routine")
    assert result == {"ran": True, "name": "Morning Routine", "output": "done"}


def test_run_shortcut_writes_input_file_when_input_given(monkeypatch):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: "/usr/bin/shortcuts")
    seen = {}

    def fake_run(args, **kwargs):
        from pathlib import Path
        in_idx = args.index("-i") + 1
        seen["input_content"] = Path(args[in_idx]).read_text(encoding="utf-8")
        return _proc(0)

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    shortcuts.run_shortcut("Backup Photos", input="hello world")
    assert seen["input_content"] == "hello world"


def test_run_shortcut_unknown_name_is_actionable(monkeypatch):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: "/usr/bin/shortcuts")
    monkeypatch.setattr(shortcuts.subprocess, "run",
                        lambda *a, **k: _proc(1, stderr="Shortcut 'Nope' not found"))

    result = shortcuts.run_shortcut("Nope")
    assert result["ran"] is False
    assert "list_shortcuts()" in result["error"]


def test_run_shortcut_generic_failure_reports_stderr(monkeypatch):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: "/usr/bin/shortcuts")
    monkeypatch.setattr(shortcuts.subprocess, "run",
                        lambda *a, **k: _proc(1, stderr="something broke"))

    result = shortcuts.run_shortcut("Broken Shortcut")
    assert result["ran"] is False
    assert "something broke" in result["error"]


def test_run_shortcut_requires_name():
    result = shortcuts.run_shortcut("")
    assert result["ran"] is False
    assert "empty" in result["error"]


def test_run_shortcut_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(shortcuts.platform, "system", lambda: "Linux")
    result = shortcuts.run_shortcut("Anything")
    assert result["ran"] is False
    assert "macOS" in result["error"]


# ── tier + registration ───────────────────────────────────────────


def test_list_shortcuts_is_registered_read_only():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "list_shortcuts" in tools
    assert get_tier(tools["list_shortcuts"]) == PermissionTier.READ_ONLY


def test_run_shortcut_is_registered_external_effect():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "run_shortcut" in tools
    assert get_tier(tools["run_shortcut"]) == PermissionTier.EXTERNAL_EFFECT
