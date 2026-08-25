"""send_email (agent/tools/email.py) — 0.9.3 Task 2a.

Backend ladder: Mail.app via AppleScript (primary, macOS) → himalaya CLI
(alternate, if installed). All ``osascript`` / ``himalaya`` invocations
are mocked here — no real subprocess, no real mail sent. Modeled on
``send_message``'s test shape (tier-2, actionable errors, never raises).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_agent.tools import email
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


def test_list_mailboxes_parses_delimited_accounts(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")

    def fake_run(args, **kwargs):
        return _proc(0, stdout="iCloud|||INBOX,Archive,\nGoogle|||INBOX,Spam,\n")

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    result = email.list_mailboxes()
    assert result["ok"] is True
    names = [a["name"] for a in result["accounts"]]
    assert names == ["iCloud", "Google"]
    assert "INBOX" in result["accounts"][0]["mailboxes"]


def test_list_mail_times_out_without_retrying(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")

    def fake_run(args, **kwargs):
        raise email.subprocess.TimeoutExpired(cmd=args, timeout=15)

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    result = email.list_mail(account="iCloud", mailbox="INBOX", limit=10)
    assert result["ok"] is False
    assert result["timed_out"] is True
    assert "timed out" in result["error"].lower()
    assert result["messages"] == []


def test_list_mail_requires_account_before_touching_mail_app(monkeypatch):
    monkeypatch.setattr(
        email.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("must not run osascript without an account"),
    )
    result = email.list_mail(account="", mailbox="INBOX", limit=10)
    assert result["ok"] is False
    assert result["timed_out"] is False
    assert "list_mailboxes" in result["error"]


def test_list_mail_parses_headers_and_clamps_limit(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(
            0,
            stdout="42|||Hello|||a@b.com|||Monday|||false\n",
        )

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    result = email.list_mail(account="iCloud", mailbox="INBOX", limit=99)
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["messages"][0]["id"] == "42"
    assert result["messages"][0]["subject"] == "Hello"
    assert "set endIndex to 25" in seen["script"]  # hard clamp
    assert "every message" not in seen["script"]


def test_move_mail_is_account_scoped(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(0, stdout="MOVED:1")

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.move_mail("42", "iCloud", "INBOX", "Archive")
    assert result["ok"] is True and result["success"] is True
    assert result["moved"] is True
    assert result["moved_count"] == 1
    assert "resolveMb" in seen["script"]
    assert "iCloud" in seen["script"]
    assert "Archive" in seen["script"]
    assert "every message" not in seen["script"]


def test_move_mail_rejects_non_numeric_id():
    result = email.move_mail("first", "iCloud", "INBOX", "Archive")
    assert result["ok"] is False
    assert result["success"] is False
    assert "numeric" in result["error"]


def test_send_email_is_registered_and_tier_gated():
    from jaeger_os.core.safety.permissions import PermissionTier, get_tier
    from jaeger_os.core.tools.tool_registry import get_tools

    tools = {t.name: t.fn for t in get_tools()}
    assert "send_email" in tools
    assert "batch_move" in tools
    assert "sweep_mail" in tools
    assert "read_mail" in tools
    assert "plan_mail_triage" in tools
    assert get_tier(tools["send_email"]) == PermissionTier.EXTERNAL_EFFECT
    assert get_tier(tools["batch_move"]) == PermissionTier.EXTERNAL_EFFECT
    assert get_tier(tools["sweep_mail"]) == PermissionTier.EXTERNAL_EFFECT


# ── nested mailbox resolver + aliases ──────────────────────────────


def test_alias_candidates_map_universal_trash_names():
    for raw in ("trash", "Trash", "[Gmail]/Trash", "Deleted Messages"):
        names = {n.lower() for n in email.alias_candidates(raw)}
        assert "trash" in names
        assert "deleted messages" in names
        assert "bin" in names


def test_alias_candidates_map_junk_and_archive():
    junk = {n.lower() for n in email.alias_candidates("spam")}
    assert "junk" in junk and "spam" in junk
    archive = {n.lower() for n in email.alias_candidates("archive")}
    assert "archive" in archive and "all mail" in archive


def test_list_mailboxes_walks_nested_gmail_containers(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(
            0,
            stdout="Google|||INBOX,[Gmail],[Gmail]/Trash,[Gmail]/All Mail,\n",
        )

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    result = email.list_mailboxes()
    assert result["ok"] is True and result["success"] is True
    assert result["error"] is None
    paths = result["accounts"][0]["mailboxes"]
    assert "[Gmail]/Trash" in paths
    assert "collectPaths" in seen["script"]
    assert "every message" not in seen["script"]


def test_list_mail_uses_nested_resolver(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(0, stdout="42|||Hello|||a@b.com|||Monday|||false\n")

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    result = email.list_mail(account="Google", mailbox="trash", limit=5)
    assert result["ok"] is True and result["success"] is True
    assert result["count"] == 1
    assert "resolveMb" in seen["script"]
    assert "Deleted Messages" in seen["script"]
    assert 'mailbox "trash" of account "Google"' not in seen["script"]


def test_run_applescript_envelope_on_timeout(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")

    def fake_run(args, **kwargs):
        raise email.subprocess.TimeoutExpired(cmd=args, timeout=15)

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    result = email.run_applescript("tell application \"Mail\" to get name")
    assert result["ok"] is False and result["success"] is False
    assert result["timed_out"] is True
    assert result["error"]
    assert "raw_output" in result or result.get("raw_output", "") == ""


# ── batch_move ─────────────────────────────────────────────────────


def test_batch_move_one_transaction(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(0, stdout="MOVED:3")

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.batch_move("Google", "INBOX", "trash", ["11", "12", "13"])
    assert result["ok"] is True and result["success"] is True
    assert result["moved_count"] == 3
    assert result["error"] is None
    script = seen["script"]
    assert "resolveMb" in script
    assert "11" in script and "12" in script and "13" in script
    assert script.count("osascript") == 0  # it's the AppleScript body
    assert "every message" not in script
    assert "Deleted Messages" in script  # trash alias expansion


def test_batch_move_accepts_comma_separated_ids(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(0, stdout="MOVED:2")

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.batch_move("Google", "INBOX", "[Gmail]/Trash", "21,22")
    assert result["moved_count"] == 2
    assert "21" in seen["script"] and "22" in seen["script"]


def test_batch_move_clamps_to_25(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(0, stdout="MOVED:25")

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    ids = [str(i) for i in range(1, 40)]
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.batch_move("iCloud", "INBOX", "Archive", ids)
    assert result["moved_count"] == 25
    assert "26" not in seen["script"]
    assert "25" in seen["script"]


def test_batch_move_zero_moved_is_failure(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        email.subprocess, "run", lambda *a, **k: _proc(0, stdout="MOVED:0"),
    )
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.batch_move("Google", "INBOX", "trash", ["99"])
    assert result["ok"] is False and result["success"] is False
    assert result["moved_count"] == 0
    assert result["error"]


def test_batch_move_partial_move_is_failure(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        email.subprocess, "run", lambda *a, **k: _proc(0, stdout="MOVED:1"),
    )
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.batch_move("Google", "INBOX", "trash", ["98", "99"])
    assert result["ok"] is False and result["success"] is False
    assert result["moved_count"] == 1
    assert "partial move" in result["error"]


# ── sweep + classify ───────────────────────────────────────────────


def test_classify_message_buckets():
    assert email.classify_message("notifications@github.com", "[foo] PR") == "GitHub-Noise"
    assert email.classify_message("billing@stripe.com", "Your receipt") == "Receipts"
    assert email.classify_message("alerts@bank.com", "Payment due") == "Finance"
    assert email.classify_message("noreply@shop.com", "Weekly deals") == "Trash"
    assert email.classify_message("sam@icloud.com", "Lunch tomorrow") == "Action"


def test_classify_keep_first_noreply_order_is_receipt():
    filing = email.classify_filing("noreply@amazon.com", "Your order has shipped")
    assert filing["category"] == "Receipts"
    assert filing["keep"] is True
    assert filing["destination"] == "Receipts"


def test_classify_bare_noreply_stays_action():
    filing = email.classify_filing("noreply@unknown.example", "Account update")
    assert filing["category"] == "Action"
    assert filing["keep"] is True
    assert filing["destination"] is None


def test_classify_peek_cannot_demote_receipt_via_unsubscribe_footer():
    header = email.classify_filing("orders@shop.com", "Your receipt for #42")
    # A body footer must not be allowed to flip a receipt to trash.
    peeked = {
        "category": "Trash", "keep": False, "destination": "trash",
        "confidence": "high", "verify": False,
        "reason": "promotional (unsubscribe)",
    }
    merged = email._prefer_keep(header, peeked)
    assert header["keep"] is True
    assert merged["keep"] is True
    assert merged["category"] == "Receipts"


def test_classify_github_security_is_kept():
    filing = email.classify_filing(
        "noreply@github.com", "A security vulnerability in your repo",
    )
    assert filing["keep"] is True
    assert filing["category"] == "Action"
    assert filing["destination"] is None


def test_coerce_int_rejects_bools_and_junk():
    assert email._coerce_int(True, 10, lo=0, hi=25) == 10
    assert email._coerce_int("nope", 3, lo=1, hi=25) == 3
    assert email._coerce_int("99", 10, lo=1, hi=25) == 25
    assert email._coerce_int(-4, 0, lo=0) == 0


def test_list_mail_offset_is_index_window(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(0, stdout="9|||Hi|||a@b.com|||Monday|||false\n")

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    result = email.list_mail(account="iCloud", mailbox="INBOX", limit=10, offset=25)
    assert result["ok"] is True
    assert "set startIndex to 26" in seen["script"]
    assert "set endIndex to 35" in seen["script"]
    assert result["offset"] == 25


def test_read_mail_parses_snippet(monkeypatch):
    monkeypatch.setattr(email.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(email.shutil, "which", lambda name: "/usr/bin/osascript")
    seen = {}

    def fake_run(args, **kwargs):
        seen["script"] = args[-1]
        return _proc(0, stdout="7|||Invoice|||bill@x.com|||Monday|||Total $12.00 paid\n")

    monkeypatch.setattr(email.subprocess, "run", fake_run)
    result = email.read_mail("iCloud", "INBOX", "7")
    assert result["ok"] is True and result["success"] is True
    assert result["messages"][0]["id"] == "7"
    assert "12.00" in result["messages"][0]["snippet"]
    assert "every message" not in seen["script"]
    assert "resolveMb" in seen["script"]


def test_plan_mail_triage_never_moves(monkeypatch):
    monkeypatch.setattr(email, "list_mail", lambda **kw: {
        "ok": True, "offset": 0, "next_offset": 2, "messages": [
            {"id": "1", "sender": "noreply@amazon.com", "subject": "Your order #1",
             "date": "Mon"},
            {"id": "2", "sender": "newsletter@ads.com", "subject": "Weekly deals",
             "date": "Mon"},
            {"id": "3", "sender": "sam@icloud.com", "subject": "Lunch", "date": "Mon"},
        ],
    })
    moved: list[object] = []
    monkeypatch.setattr(
        email, "_batch_move_impl",
        lambda *a, **k: moved.append(a) or {"ok": True, "moved_count": 1},
    )
    monkeypatch.setattr(
        email, "_read_mail_impl",
        lambda *a, **k: {"ok": True, "messages": [
            {"id": "1", "snippet": "Order total $41.00. Tracking number 1Z"},
        ]},
    )
    result = email.plan_mail_triage("iCloud", "INBOX", offset=0, peek=True)
    assert result["ok"] is True
    assert moved == []
    assert result["after_move_offset"] == 0
    by_id = {i["id"]: i for i in result["items"]}
    assert by_id["1"]["keep"] is True and by_id["1"]["category"] == "Receipts"
    assert by_id["2"]["keep"] is False and by_id["2"]["category"] == "Trash"
    assert by_id["3"]["keep"] is True and by_id["3"]["destination"] is None


def test_sweep_mail_dry_run_does_not_move(monkeypatch):
    monkeypatch.setattr(email, "list_mailboxes", lambda: {
        "ok": True, "accounts": [{"name": "Google", "mailboxes": ["INBOX"]}],
    })
    monkeypatch.setattr(email, "list_mail", lambda **kw: {
        "ok": True, "messages": [
            {"id": "1", "sender": "notifications@github.com", "subject": "PR"},
            {"id": "2", "sender": "sam@icloud.com", "subject": "Lunch"},
        ],
    })
    calls: list[object] = []
    monkeypatch.setattr(
        email, "_batch_move_impl",
        lambda *a, **k: calls.append(a) or {"ok": True, "moved_count": 1},
    )
    result = email.sweep_mail(dry_run=True)
    assert result["ok"] is True and result["success"] is True
    assert result["dry_run"] is True
    assert result["moved_count"] == 0
    assert calls == []
    cats = {c["category"] for c in result["candidates"]}
    assert cats == {"GitHub-Noise", "Action"}


def test_sweep_mail_execute_files_only_noise(monkeypatch):
    monkeypatch.setattr(email, "list_mail", lambda **kw: {
        "ok": True, "messages": [
            {"id": "1", "sender": "notifications@github.com", "subject": "PR"},
            {"id": "2", "sender": "sam@icloud.com", "subject": "Lunch"},
            {"id": "3", "sender": "newsletter@ads.com", "subject": "Weekly deals"},
            {"id": "4", "sender": "noreply@amazon.com", "subject": "Your order #9"},
            {"id": "5", "sender": "newsletter@shop.com", "subject": "Your receipt"},
            {"id": "6", "sender": "notifications@github.com", "subject": "New sign in"},
        ],
    })
    moved: list[tuple] = []

    def fake_batch(account, source, target, ids):
        moved.append((account, source, target, list(ids)))
        return {"ok": True, "moved_count": len(ids), "success": True}

    monkeypatch.setattr(email, "_batch_move_impl", fake_batch)
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.sweep_mail(account="Google", dry_run=False)
    assert result["ok"] is True
    assert result["dry_run"] is False
    by_target: dict[str, set[str]] = {}
    for _acc, _src, target, ids in moved:
        by_target.setdefault(target, set()).update(ids)
    assert by_target["GitHub-Noise"] == {"1"}
    assert by_target["trash"] == {"3"}
    filed = {i for ids in by_target.values() for i in ids}
    assert "2" not in filed
    assert "4" not in filed  # receipt stays put
    assert "5" not in filed  # promotional sender alone never trashes
    assert "6" not in filed  # GitHub security/auth stays in inbox


def test_sweep_mail_partial_batch_is_failure(monkeypatch):
    monkeypatch.setattr(email, "list_mail", lambda **kw: {
        "ok": True, "messages": [
            {"id": "1", "sender": "newsletter@ads.com", "subject": "Weekly deals"},
            {"id": "2", "sender": "deals@ads.com", "subject": "Daily deals"},
        ],
    })
    monkeypatch.setattr(email, "_batch_move_impl", lambda *a, **k: {
        "ok": True, "success": True, "moved_count": 1, "error": None,
    })
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.sweep_mail(account="Google", dry_run=False)
    assert result["ok"] is False
    assert result["moved_count"] == 0
    assert result["moved"] == []
    assert "moved 1 of 2" in result["error"]


def test_schedule_inbox_sweeper_writes_twice_daily_cron(monkeypatch):
    captured = {}

    def fake_add(**kwargs):
        captured.update(kwargs)
        return {
            "name": kwargs["name"],
            "cron": kwargs["cron_expr"],
            "prompt": kwargs["prompt"],
        }

    monkeypatch.setattr("jaeger_agent.memory.memory.add_schedule", fake_add)
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        result = email.schedule_inbox_sweeper(morning_hour=8, evening_hour=18)
    assert result["ok"] is True and result["scheduled"] is True
    assert captured["name"] == "inbox-sweeper"
    assert captured["cron_expr"] == "0 8,18 * * *"
    assert "sweep_mail" in captured["prompt"]


def test_mail_tool_cli_list_get_and_batch_move(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[4]
        / "packages/jaeger-agent/jaeger_agent/skills/email"
        / "macos-mail-organizer/scripts/mail_tool.py"
    )
    spec = importlib.util.spec_from_file_location("mail_tool_cli", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(
        "jaeger_agent.tools.email.list_mailboxes",
        lambda: {"ok": True, "success": True, "accounts": [{"name": "Google"}]},
    )
    monkeypatch.setattr(
        "jaeger_agent.tools.email.list_mail",
        lambda account, mailbox="INBOX", limit=10, unread_only=False, offset=0: {
            "ok": True, "success": True, "count": 1,
            "account": account, "mailbox": mailbox, "limit": limit,
            "messages": [{"id": "1"}],
        },
    )
    monkeypatch.setattr(
        "jaeger_agent.tools.email.batch_move",
        lambda account, source, target, ids: {
            "ok": True, "success": True, "moved_count": 2,
            "account": account, "source": source, "target": target,
            "message_ids": ids,
        },
    )
    assert mod.main(["list"]) == 0
    assert mod.main(["get", "Google", "INBOX", "5"]) == 0
    assert mod.main(["batch_move", "Google", "INBOX", "trash", "1,2"]) == 0
    assert mod.main(["aliases", "trash"]) == 0
