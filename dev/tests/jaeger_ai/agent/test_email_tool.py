"""send_email (agent/tools/email.py) — 0.9.3 Task 2a.

Backend ladder: Mail.app via AppleScript (primary, macOS) → himalaya CLI
(alternate, if installed). All ``osascript`` / ``himalaya`` invocations
are mocked here — no real subprocess, no real mail sent. Modeled on
``send_message``'s test shape (tier-2, actionable errors, never raises).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.agent.tools import email
from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def _allow_all_tier_checks():
    """``send_email`` carries its own tier gate (@requires_tier, applied
    directly like send_message — see the module docstring). These tests
    exercise the backend-ladder LOGIC, not the gate itself (that's
    test_tier_gating.py's job), so install a permissive policy."""
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        yield


# ── Mail.app backend (AppleScript) ───────────────────────────────────


def test_send_email_uses_mail_app_when_an_account_is_configured(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        script = args[-1] if args[0] == "osascript" else ""
        if "get name of every account" in script:
            return _proc(0, stdout="iCloud, Work\n")
        if "send newMessage" in script:
            return _proc(0, stdout="")
        raise AssertionError(f"unexpected osascript call: {script!r}")

    monkeypatch.setattr(email.subprocess, "run", fake_run)

    result = email.send_email("friend@example.com", "Hi", "Body text")
    assert result == {
        "sent": True, "backend": "mail_app",
        "to": "friend@example.com", "subject": "Hi",
    }
    # account probe + compose/send — exactly two osascript round-trips.
    assert len(calls) == 2
    assert calls[0][0] == "osascript" and calls[1][0] == "osascript"


def test_send_email_mail_app_compose_script_includes_recipient_subject_body(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: f"/usr/bin/{name}")
    seen_scripts: list[str] = []

    def fake_run(args, **kwargs):
        script = args[-1]
        seen_scripts.append(script)
        if "get name of every account" in script:
            return _proc(0, stdout="iCloud\n")
        return _proc(0)

    monkeypatch.setattr(email.subprocess, "run", fake_run)

    email.send_email("bob@example.com", "Lunch?", "Free at noon?", cc="cc@example.com")
    compose_script = seen_scripts[-1]
    assert "bob@example.com" in compose_script
    assert "Lunch?" in compose_script
    assert "Free at noon?" in compose_script
    assert "cc@example.com" in compose_script
    assert "cc recipient" in compose_script


def test_send_email_mail_app_escapes_quotes_in_subject_and_body(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: f"/usr/bin/{name}")
    seen_scripts: list[str] = []

    def fake_run(args, **kwargs):
        script = args[-1]
        seen_scripts.append(script)
        if "get name of every account" in script:
            return _proc(0, stdout="iCloud\n")
        return _proc(0)

    monkeypatch.setattr(email.subprocess, "run", fake_run)

    email.send_email('a@b.com', 'She said "hi"', 'Quote: "ok"')
    compose_script = seen_scripts[-1]
    assert 'She said \\"hi\\"' in compose_script
    assert 'Quote: \\"ok\\"' in compose_script


def test_send_email_mail_app_actionable_error_when_no_account_configured(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    # osascript is present but no himalaya — forces the "neither backend" path.
    monkeypatch.setattr(email.shutil, "which",
                         lambda name: "/usr/bin/osascript" if name == "osascript" else None)

    def fake_run(args, **kwargs):
        return _proc(0, stdout="")  # empty account list

    monkeypatch.setattr(email.subprocess, "run", fake_run)

    result = email.send_email("friend@example.com", "Hi", "Body")
    assert result["sent"] is False
    assert "Mail.app has no email account configured" in result["error"]
    assert "himalaya" in result["error"]


def test_send_email_mail_app_send_failure_reports_osascript_stderr(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which",
                         lambda name: "/usr/bin/osascript" if name == "osascript" else None)

    def fake_run(args, **kwargs):
        script = args[-1]
        if "get name of every account" in script:
            return _proc(0, stdout="iCloud\n")
        return _proc(1, stderr="Mail got an error: not authorized")

    monkeypatch.setattr(email.subprocess, "run", fake_run)

    result = email.send_email("friend@example.com", "Hi", "Body")
    assert result["sent"] is False
    assert "not authorized" in result["error"]


def test_send_email_skips_mail_app_on_non_macos(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Linux")
    monkeypatch.setattr(email.shutil, "which", lambda name: None)

    result = email.send_email("friend@example.com", "Hi", "Body")
    assert result["sent"] is False
    assert "macOS" in result["error"]


# ── himalaya backend (detection + fallback) ──────────────────────────


def test_send_email_falls_back_to_himalaya_when_mail_app_unconfigured(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")

    def fake_which(name):
        return None if name == "osascript" else f"/opt/homebrew/bin/{name}"

    # osascript is technically "found" for the probe but Mail has no account.
    monkeypatch.setattr(email.shutil, "which",
                         lambda name: "/usr/bin/osascript" if name == "osascript" else "/opt/bin/himalaya")

    def fake_run(args, **kwargs):
        if args[0] == "osascript":
            return _proc(0, stdout="")  # no accounts
        if args[0] == "/opt/bin/himalaya":
            assert args[1:] == ["message", "send"]
            assert "friend@example.com" in kwargs.get("input", "")
            return _proc(0, stdout="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(email.subprocess, "run", fake_run)

    result = email.send_email("friend@example.com", "Hi", "Body")
    assert result == {
        "sent": True, "backend": "himalaya",
        "to": "friend@example.com", "subject": "Hi",
    }


def test_send_email_himalaya_not_installed_is_detected_and_reported(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: None)  # nothing installed

    def fake_run(args, **kwargs):
        return _proc(0, stdout="")  # Mail: no accounts either

    monkeypatch.setattr(email.subprocess, "run", fake_run)

    result = email.send_email("friend@example.com", "Hi", "Body")
    assert result["sent"] is False
    assert "himalaya CLI not found on PATH" in result["error"]


def test_send_email_himalaya_message_includes_cc(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Linux")  # skip Mail.app entirely
    monkeypatch.setattr(email.shutil, "which",
                         lambda name: "/opt/bin/himalaya" if name == "himalaya" else None)
    captured = {}

    def fake_run(args, **kwargs):
        captured["input"] = kwargs.get("input", "")
        return _proc(0)

    monkeypatch.setattr(email.subprocess, "run", fake_run)

    email.send_email("a@b.com", "Subj", "Body", cc="c@d.com")
    assert "c@d.com" in captured["input"]


# ── validation ─────────────────────────────────────────────────────


def test_send_email_requires_to_and_subject():
    assert email.send_email("", "Subj", "Body")["sent"] is False
    assert email.send_email("a@b.com", "", "Body")["sent"] is False


# ── tier + registration ───────────────────────────────────────────


def test_send_email_is_registered_and_tier_gated():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "send_email" in tools
    assert get_tier(tools["send_email"]) == PermissionTier.EXTERNAL_EFFECT
