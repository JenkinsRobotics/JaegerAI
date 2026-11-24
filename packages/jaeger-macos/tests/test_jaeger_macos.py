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
