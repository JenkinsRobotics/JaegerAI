"""Fast native Calendar / Reminders / Contacts via the Jaeger PIM helper.

``~/.jaeger/bin/JaegerPIM.app`` (source: jaeger_ai/interfaces/macos-pim) uses
EventKit and the Contacts framework instead of AppleScript round-trips to
Calendar.app / Contacts.app, which timed out at 60s / 10s (audit parity P7).
It is launched through LaunchServices so the macOS privacy prompt names
"Jaeger PIM". ``run`` returns None when the helper is missing or fails to
start, so callers fall back to their AppleScript path.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

HELPER_TIMEOUT_S = 25


def helper_app() -> Path | None:
    root = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger").expanduser()
    app = Path(os.environ.get("JAEGER_PIM_APP") or root / "bin/JaegerPIM.app")
    return app if (app / "Contents/MacOS/JaegerPIM").exists() else None


def run(command: str, **opts: Any) -> dict | None:
    data = _run(command, background=True, **opts)
    # A background (-g) launch cannot show the macOS privacy prompt: EventKit
    # answers "not granted" at once while access is still "not determined".
    # Ask once in the foreground so the owner sees the prompt (2026-11-16).
    if data and not data.get("ok") and "not granted" in str(data.get("error", "")):
        status = _run("status", background=True) or {}
        key = {"events": "calendar", "create-event": "calendar",
               "reminders": "reminders", "contacts": "contacts"}.get(command)
        if key and status.get(key) == 0:
            data = _run(command, background=False, timeout=90, **opts) or data
    return data


def _run(command: str, background: bool = True, timeout: int = HELPER_TIMEOUT_S, **opts: Any) -> dict | None:
    app = helper_app()
    if app is None:
        return None
    fd, out = tempfile.mkstemp(prefix="jaeger-pim-", suffix=".json")
    os.close(fd)
    os.unlink(out)
    argv = ["open", "-W"] + (["-g"] if background else []) + ["-n", "-a", str(app), "--args", command]
    for key, value in opts.items():
        if value is None or value is False:
            continue
        flag = "--" + key.replace("_", "-")
        argv += [flag] if value is True else [flag, str(value)]
    argv += ["--out", out]
    try:
        subprocess.run(argv, check=False, capture_output=True, timeout=timeout)
        data = json.loads(Path(out).read_text("utf-8"))
        return data if isinstance(data, dict) else None
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Jaeger PIM did not answer in {timeout}s (a privacy prompt may be waiting on the Mac)"}
    except (OSError, ValueError):
        return None
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass
