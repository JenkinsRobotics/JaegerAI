"""macOS iMessage / SMS adapter.

Reads new incoming messages from ~/Library/Messages/chat.db (SQLite) and
sends replies via AppleScript to Messages.app. Works for both iMessage
and SMS (when the host Mac has Text Message Forwarding enabled with an
iPhone).

  • Requires **Full Disk Access** for the Python interpreter (System
    Settings → Privacy & Security → Full Disk Access → add Terminal /
    iTerm / your IDE / `.venv/bin/python`).
  • Requires **Automation access** for Messages.app the first time
    AppleScript drives it — macOS will prompt.

Configure who can talk to it via IMESSAGE_ALLOWED_HANDLES (comma-separated
phone numbers or Apple IDs, e.g. "+15551234567,name@icloud.com"). With
no allowlist the bridge refuses to send anything, since opening it to
every random sender on iMessage is a bad idea by default.
"""

from __future__ import annotations

import os
import shlex
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CHAT_DB = Path("~/Library/Messages/chat.db").expanduser()
POLL_INTERVAL_S = 2.0


def _parse_allowed_handles() -> set[str]:
    raw = os.environ.get("IMESSAGE_ALLOWED_HANDLES", "").strip()
    if not raw:
        return set()
    return {h.strip() for h in raw.split(",") if h.strip()}


def _cocoa_to_iso(date_ns: int) -> str:
    """Apple stores message dates as nanoseconds since 2001-01-01 UTC."""
    if date_ns is None:
        return ""
    epoch = datetime(2001, 1, 1, tzinfo=timezone.utc).timestamp()
    return datetime.fromtimestamp(epoch + date_ns / 1e9, tz=timezone.utc).isoformat(timespec="seconds")


class IMessageBridge:
    """Polls chat.db for incoming texts and replies via AppleScript.

    Same `handler(text) -> reply` callback contract as DiscordBridge.
    Replies use Messages.app's iMessage service preferentially; you can
    override via IMESSAGE_SERVICE (e.g. "SMS" to force SMS routing).
    """

    def __init__(self, handler: Callable[[str], str],
                 llm_lock: threading.Lock | None = None,
                 allowed_handles: set[str] | None = None,
                 bus: Any = None,
                 admin_ids: set[str] | None = None) -> None:
        if not CHAT_DB.exists():
            raise RuntimeError(f"chat.db not found at {CHAT_DB} — iMessage not configured "
                               "on this Mac (and the agent needs Full Disk Access to read it)")

        self._handler = handler
        self._llm_lock = llm_lock
        # Instance-folder first: the allowlist is passed by the in-process
        # activator (from <instance>/credentials/); env is a legacy fallback.
        # iMessage has no bot token — it uses the local Messages app.
        self._allowed = allowed_handles if allowed_handles is not None else _parse_allowed_handles()
        self._bus = bus
        # The owner's certified handles (the only admin); others conversation-only.
        self._admin = {str(a) for a in (admin_ids or set())}
        self._awaiting: dict[str, str] = {}   # handle → pending approval id
        self._service = os.environ.get("IMESSAGE_SERVICE", "iMessage").strip()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_rowid = self._current_max_rowid()

    # ----- lifecycle -----
    def start(self) -> None:
        if self._thread is not None:
            return
        if not self._allowed:
            print(
                "[imessage] refusing to start: set IMESSAGE_ALLOWED_HANDLES to "
                "a comma-separated list of approved handles (phone numbers or Apple IDs)",
                flush=True,
            )
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="imessage-bridge")
        self._thread.start()
        from .. import register_bridge
        register_bridge("imessage", self)
        if self._bus is not None:
            try:
                from jaeger_os.core.messages import AgentRequest
                self._bus.subscribe(AgentRequest.topic, self._on_agent_request)
            except Exception:  # noqa: BLE001 — approvals-over-imessage is best-effort
                pass
        print(f"[imessage] watching chat.db, allowlist: {sorted(self._allowed)}", flush=True)

    def _on_agent_request(self, msg: Any) -> None:
        """Surface a mid-turn approval to the originating handle; their next
        message becomes the AgentResponse (see _handle_row)."""
        from .. import _messaging
        out = _messaging.request_to_prompt("imessage", msg, self._awaiting)
        if out is None:
            return
        recipient, text = out
        try:
            self._send(recipient, text)
        except Exception:  # noqa: BLE001
            self._awaiting.pop(recipient, None)

    def stop(self) -> None:
        from .. import deregister_bridge
        deregister_bridge("imessage")
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ----- outbound: agent-initiated messages -----
    def send(self, recipient: str, text: str) -> dict[str, Any]:
        """Send `text` to an iMessage/SMS recipient (phone number or Apple ID).

        The recipient must be in IMESSAGE_ALLOWED_HANDLES — we refuse to
        cold-text strangers from this tool, period. Returns
        {sent: True, recipient} on success or {sent: False, error: "..."}.
        """
        if recipient not in self._allowed:
            return {"sent": False, "error": f"recipient {recipient!r} not in IMESSAGE_ALLOWED_HANDLES"}
        try:
            self._send(recipient, text)
        except Exception as exc:
            return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"sent": True, "recipient": recipient}

    # ----- internals -----
    def _connect(self) -> sqlite3.Connection:
        """Open chat.db read-only via URI so we never accidentally write."""
        return sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True, timeout=5.0)

    def _current_max_rowid(self) -> int:
        try:
            with self._connect() as db:
                cur = db.execute("SELECT COALESCE(MAX(ROWID), 0) FROM message")
                return int(cur.fetchone()[0])
        except sqlite3.Error as exc:
            print(f"[imessage] chat.db read failed (Full Disk Access?): {exc}", flush=True)
            return 0

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                rows = self._fetch_new()
            except sqlite3.Error as exc:
                print(f"[imessage] poll error: {exc}", flush=True)
                rows = []
            for row in rows:
                if self._stop.is_set():
                    break
                self._handle_row(row)
            self._stop.wait(POLL_INTERVAL_S)

    def _fetch_new(self) -> list[dict[str, Any]]:
        sql = """
            SELECT m.ROWID, m.text, m.date, m.is_from_me, h.id AS handle
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE m.ROWID > ? AND m.is_from_me = 0
            ORDER BY m.ROWID ASC
        """
        with self._connect() as db:
            cur = db.execute(sql, (self._last_rowid,))
            rows = [
                {
                    "rowid": int(r[0]),
                    "text": r[1] or "",
                    "date_ns": int(r[2] or 0),
                    "is_from_me": int(r[3] or 0),
                    "handle": (r[4] or "").strip(),
                }
                for r in cur.fetchall()
            ]
        if rows:
            self._last_rowid = max(r["rowid"] for r in rows)
        return rows

    def _handle_row(self, row: dict[str, Any]) -> None:
        handle = row["handle"]
        text = (row["text"] or "").strip()
        if not handle or not text:
            return
        if handle not in self._allowed:
            print(f"[imessage] ignoring message from {handle!r} (not in allowlist)", flush=True)
            return
        print(f"[imessage] from {handle!r} ({_cocoa_to_iso(row['date_ns'])}): {text[:100]!r}", flush=True)
        session_key = f"imessage:{handle}"
        from jaeger_os.core.runtime import modes
        from jaeger_os.core.safety import session_trust
        from .. import _messaging
        is_admin = str(handle) in self._admin
        session_trust.mark_session(session_key, is_admin)
        # A pending approval? the reply IS the answer (don't run a turn).
        if _messaging.reply_as_approval("imessage", handle, text, self._awaiting, self._bus):
            self._send(handle, "✓ got it")
            return
        # Slash commands — OWNER-ONLY; handled here, not sent to the LLM.
        if _messaging.is_slash(text):
            if not is_admin:
                self._send(handle, _messaging.SLASH_DENIED)
                return
            plan = _messaging.mode_command(text)
            if not plan:
                self._send(handle, _messaging.SLASH_UNKNOWN)
            elif "reply" in plan:
                self._send(handle, plan["reply"])
            else:
                self._send(handle, plan["ack"])
                res = modes.set_mode(plan["switch"])   # sync — pauses the poll thread (ok)
                self._send(handle, _messaging.mode_result(res, plan["switch"]))
            return
        try:
            if self._llm_lock is not None:
                with self._llm_lock:
                    reply = self._call_handler(text, session_key) or ""
            else:
                reply = self._call_handler(text, session_key) or ""
        except Exception as exc:
            reply = f"(agent error: {type(exc).__name__}: {exc})"
        if reply:
            self._send(handle, reply)

    def _call_handler(self, text: str, session_key: str) -> str:
        try:
            return self._handler(text, session_key=session_key) or ""
        except TypeError:
            return self._handler(text) or ""

    def _send(self, handle: str, message: str) -> None:
        # AppleScript via osascript; quote the strings the AppleScript way
        # (single backslash-then-quote inside a quoted string).
        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace('"', '\\"')

        script = f'''
            tell application "Messages"
                set targetService to first service whose service type is {self._service}
                set targetBuddy to buddy "{esc(handle)}" of targetService
                send "{esc(message)}" to targetBuddy
            end tell
        '''
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True, capture_output=True, text=True, timeout=15,
            )
            print(f"[imessage] → {handle}: {message[:80]!r}", flush=True)
        except subprocess.CalledProcessError as exc:
            print(f"[imessage] send failed for {handle!r}: {exc.stderr.strip()}", flush=True)
        except subprocess.TimeoutExpired:
            print(f"[imessage] send timed out for {handle!r}", flush=True)
