from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

from jaeger_macos import (
    alias_candidates,
    appleevents_lock,
    decode_attributed_body,
    escape_applescript,
    resolve_mailbox_call,
)


def _child_hold_lock(lock_dir: str, log_file: str, worker_id: str) -> None:
    os.environ["JAEGER_APPLEEVENTS_LOCK_DIR"] = lock_dir
    with appleevents_lock("mail"):
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(f"enter:{worker_id}\n")
        time.sleep(0.12)
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(f"exit:{worker_id}\n")


def test_cross_process_appleevents_lock_serializes_processes(tmp_path: Path) -> None:
    lock_dir = str(tmp_path / "locks")
    log_file = str(tmp_path / "events.log")
    ctx = multiprocessing.get_context("spawn")
    p1 = ctx.Process(target=_child_hold_lock, args=(lock_dir, log_file, "p1"))
    p2 = ctx.Process(target=_child_hold_lock, args=(lock_dir, log_file, "p2"))
    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)
    assert p1.exitcode == 0 and p2.exitcode == 0
    lines = Path(log_file).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    # Must strictly serialize: enter:X, exit:X, enter:Y, exit:Y (never interleaved!)
    first = lines[0].split(":")[1]
    second = lines[2].split(":")[1]
    assert lines == [f"enter:{first}", f"exit:{first}", f"enter:{second}", f"exit:{second}"]


def test_mail_and_imessage_helpers() -> None:
    assert escape_applescript('a "b" \\c') == 'a \\"b\\" \\\\c'
    assert "Deleted Messages" in alias_candidates("trash")
    assert "resolveMb" in resolve_mailbox_call("targetMb", "Google", "trash")
    payload = b"prefixNSString\x01\x02+\x05hello"
    assert decode_attributed_body(payload) == "hello"


def test_apple_calendar_reminders_notes_with_mock_runner(monkeypatch) -> None:
    import types
    from jaeger_macos import (
        appleevents,
        complete_reminder,
        create_calendar_event,
        create_note,
        create_reminder,
        list_calendars,
        list_note_folders,
        list_reminder_lists,
        list_reminders,
        list_upcoming_events,
        read_note,
        search_notes,
    )

    monkeypatch.setattr(appleevents.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(appleevents.shutil, "which", lambda _x: "/usr/bin/osascript")

    def _fake(stdout: str):
        def _run(_cmd, **_kwargs):
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        return _run

    assert list_calendars(runner=_fake("Work\nPersonal\n"))["calendars"] == ["Work", "Personal"]
    evs = list_upcoming_events(
        days=5,
        runner=_fake("Work\x1fStandup\x1f2026-11-28T09:00:00\x1f2026-11-28T09:30:00\x1fLab"),
    )
    assert evs["ok"] is True and evs["events"][0]["summary"] == "Standup"

    created = create_calendar_event(
        summary="Build Review",
        start_iso="2026-11-28T14:00:00",
        duration_minutes=45,
        runner=_fake("Work\x1fev-123"),
    )
    assert created["ok"] is True and created["uid"] == "ev-123"

    assert list_reminder_lists(runner=_fake("Reminders\nShop\n"))["lists"] == ["Reminders", "Shop"]
    rems = list_reminders(runner=_fake("Shop\x1fr1\x1fOrder servos\x1ffalse\x1f"))
    assert rems["ok"] is True and rems["reminders"][0]["title"] == "Order servos"
    assert create_reminder(title="Test motor", runner=_fake("Shop\x1fr2"))["id"] == "r2"
    assert complete_reminder(title="Test motor", runner=_fake("completed\x1fShop"))["completed"] is True

    assert list_note_folders(runner=_fake("Notes\nRobotics\n"))["folders"] == ["Notes", "Robotics"]
    found = search_notes(query="BOM", runner=_fake("Robotics\x1fn1\x1fJP01 BOM\x1f2026-11-27T10:00:00"))
    assert found["ok"] is True and found["notes"][0]["title"] == "JP01 BOM"
    rd = read_note(title="JP01 BOM", runner=_fake("Robotics\x1fn1\x1f<h1>JP01 BOM</h1><div>Servo x4</div>"))
    assert rd["ok"] is True and "Servo x4" in rd["content"]
    cn = create_note(title="Spec", body="Line 1\nLine 2", runner=_fake("Notes\x1fn2"))
    assert cn["ok"] is True and cn["id"] == "n2"


def test_computer_use_guard_and_audit_record() -> None:
    from jaeger_macos import ComputerUseAuditRecord, check_app_automation_allowed

    assert check_app_automation_allowed("1Password").allowed is False
    assert check_app_automation_allowed("Keychain Access").allowed is False
    assert check_app_automation_allowed("System Settings").allowed is False
    assert check_app_automation_allowed("Safari", window_title="1Password Vault").allowed is False
    assert check_app_automation_allowed("Terminal", window_title="JaegerAI").allowed is True

    rec = ComputerUseAuditRecord(
        action="click",
        target_app="Terminal",
        model_decision={"tool": "desktop_click", "x": 10, "y": 20},
        authorization={"mode": "ask", "approved": True},
    )
    rec.mark_delivered(details="cg_event_posted")
    # Delivered input must NOT automatically mark business_verification as verified!
    assert rec.execution["status"] == "delivered"
    assert rec.business_verification["status"] == "unverified"
    rec.mark_verified(evidence="button_state_active")
    assert rec.business_verification["status"] == "verified"
