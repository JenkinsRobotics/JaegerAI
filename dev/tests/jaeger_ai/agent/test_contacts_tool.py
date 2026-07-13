"""contacts.py (agent/tools/contacts.py) — 0.9.3 mac-native suite.

All ``osascript`` invocations are mocked — no real Contacts.app call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.agent.tools import contacts
from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


def test_lookup_contact_parses_matches(monkeypatch):
    monkeypatch.setattr(contacts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(contacts.shutil, "which", lambda name: "/usr/bin/osascript")

    ff, fv, fr = contacts._FIELD_SEP, contacts._VALUE_SEP, contacts._RECORD_SEP
    raw = f"Sam Smith{ff}sam@x.com{fv}sam@work.com{fv}{ff}555-1234{fv}{fr}"

    monkeypatch.setattr(contacts.subprocess, "run", lambda *a, **k: _proc(0, stdout=raw))
    result = contacts.lookup_contact("Sam")
    assert result["found"] is True
    assert result["count"] == 1
    match = result["matches"][0]
    assert match["name"] == "Sam Smith"
    assert match["emails"] == ["sam@x.com", "sam@work.com"]
    assert match["phones"] == ["555-1234"]


def test_lookup_contact_no_match_is_actionable(monkeypatch):
    monkeypatch.setattr(contacts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(contacts.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(contacts.subprocess, "run", lambda *a, **k: _proc(0, stdout=""))

    result = contacts.lookup_contact("Nobody")
    assert result["found"] is False
    assert "Nobody" in result["error"]


def test_lookup_contact_requires_name():
    result = contacts.lookup_contact("")
    assert result["found"] is False
    assert "empty" in result["error"]


def test_lookup_contact_escapes_quotes(monkeypatch):
    monkeypatch.setattr(contacts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(contacts.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = []

    def fake_run(args, **kwargs):
        seen.append(args[-1])
        return _proc(0, stdout="")

    monkeypatch.setattr(contacts.subprocess, "run", fake_run)
    contacts.lookup_contact('Sam "The Man"')
    assert 'Sam \\"The Man\\"' in seen[-1]


def test_lookup_contact_osascript_failure_reported(monkeypatch):
    monkeypatch.setattr(contacts.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(contacts.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(contacts.subprocess, "run",
                        lambda *a, **k: _proc(1, stderr="Contacts got an error"))
    result = contacts.lookup_contact("Sam")
    assert result["found"] is False
    assert "Contacts got an error" in result["error"]


def test_lookup_contact_skipped_on_non_macos(monkeypatch):
    monkeypatch.setattr(contacts.platform, "system", lambda: "Linux")
    result = contacts.lookup_contact("Sam")
    assert result["found"] is False
    assert "macOS" in result["error"]


def test_lookup_contact_is_registered_read_only():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "lookup_contact" in tools
    assert get_tier(tools["lookup_contact"]) == PermissionTier.READ_ONLY
