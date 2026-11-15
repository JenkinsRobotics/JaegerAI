"""Gateway side of Droid mode: offer an unprompted line to the droid (stdlib only).

The droid's gate decides in code: ``speak`` (Matthew is present and facing the
Mac Studio), ``push`` (away, guests present, night, or quiet mode: send it to
the phone instead) or ``quiet``. Returns None when the droid isn't running.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
from pathlib import Path

STATE = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger")
SOCK = STATE / "run" / "droid" / "control.sock"


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("droid", timeout=timeout)
        self.path_ = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path_)


def droid_kind(kind: str, source: str = "", level: str = "") -> str:
    """Map an initiative kind onto the gate's value classes."""
    k = f"{kind} {source}".lower()
    if "approval" in k:  # includes the heartbeat's approval_check_in
        return "approval"
    if "follow" in k or "commit" in k or "remind" in k:
        return "follow_up"
    if "finish" in k or "done" in k or "complete" in k or "job" in k:
        return "job_done"
    if "small" in k or "chat" in k:
        return "small_talk"
    if level == "immediate":
        return "follow_up"
    return "check_in" if "check" in k or "heartbeat" in k else "info"


def offer(text: str, *, kind: str = "info", private: bool = True, timeout: float = 2.5) -> dict | None:
    if not SOCK.exists():
        return None
    try:
        conn = _UnixConnection(str(SOCK), timeout)
        conn.request("POST", "/proactive", body=json.dumps({"text": text, "kind": kind, "private": private}),
                     headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read() or b"{}")
        conn.close()
        return data if isinstance(data, dict) and data.get("action") else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
