"""iMessage self-chat transport (Messages.app on this Mac).

Only the owner's own 1:1 self-chat is ever read (``chat.chat_identifier`` in
``self_handles``), and the only send target is ``send_to`` (one of the owner's
own handles). This sends as the owner, so it never addresses anyone else.

Reading ``~/Library/Messages/chat.db`` needs Full Disk Access for the relay's
Python; sending needs Automation permission for Messages (macOS prompts once).
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from jaeger_macos.imessage import SEND_IMESSAGE_SCRIPT as _SEND_SCRIPT, decode_attributed_body
from jaeger_macos.appleevents import appleevents_lock

CHAT_DB = Path("~/Library/Messages/chat.db").expanduser()


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _digest(text: str) -> str:
    return hashlib.sha256(_norm(text).encode()).hexdigest()[:20]


class IMessageSelfChat:
    name = "imessage"

    def __init__(self, cfg: dict[str, Any], state: dict[str, Any]) -> None:
        self.cfg = cfg
        self.handles = {h.strip() for h in cfg.get("self_handles") or [] if str(h).strip()}
        self.send_to = (cfg.get("send_to") or "").strip()
        self.service = cfg.get("service") or "iMessage"
        self.state = state
        self.last_rowid = int(state.get("last_rowid") or 0)
        self._sent: dict[str, float] = {}       # digest → time (echo suppression)
        self._recent_in: dict[str, float] = {}  # digest → time (sent+received dedupe)
        self.error: str | None = None

    # -- status ---------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.handles) and self.send_to in self.handles

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "send_to": self.send_to or None,
            "self_handles": sorted(self.handles),
            "error": self.error,
            "last_rowid": self.last_rowid,
        }

    # -- inbound --------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True, timeout=5.0)

    def prime(self) -> None:
        """Start from 'now' on first run so old history is never replayed."""
        if self.last_rowid:
            return
        with self._connect() as db:
            self.last_rowid = int(db.execute("SELECT COALESCE(MAX(ROWID),0) FROM message").fetchone()[0])

    def poll(self, prefix: str) -> list[dict[str, Any]]:
        """New owner messages from the self-chat, oldest first."""
        if not self.configured:
            return []
        try:
            self.prime()
            marks = ",".join("?" * len(self.handles))
            sql = f"""
                SELECT m.ROWID, m.text, m.attributedBody, m.is_from_me, m.associated_message_type,
                       m.item_type, c.chat_identifier
                FROM message m
                JOIN chat_message_join j ON j.message_id = m.ROWID
                JOIN chat c ON c.ROWID = j.chat_id
                WHERE m.ROWID > ? AND c.chat_identifier IN ({marks}) AND c.style = 45
                ORDER BY m.ROWID ASC
            """
            with self._connect() as db:
                rows = db.execute(sql, (self.last_rowid, *sorted(self.handles))).fetchall()
                # Self-chat must be 1:1 with the owner's own handle only.
            self.error = None
        except sqlite3.Error as exc:
            self.error = f"chat.db unreadable ({exc}); grant Full Disk Access to the relay's Python"
            return []
        out: list[dict[str, Any]] = []
        now = time.time()
        self._sent = {k: v for k, v in self._sent.items() if now - v < 900}
        self._recent_in = {k: v for k, v in self._recent_in.items() if now - v < 120}
        for rowid, text, body, _from_me, assoc, item_type, _chat in rows:
            self.last_rowid = max(self.last_rowid, int(rowid))
            if assoc or item_type:  # tapbacks, renames, etc.
                continue
            msg = (text or "").strip() or decode_attributed_body(body)
            if not msg or msg.startswith(prefix.strip()):
                continue
            digest = _digest(msg)
            if digest in self._sent or digest in self._recent_in:
                continue  # our own echo, or the second copy of a self-sent message
            self._recent_in[digest] = now
            out.append({"id": str(rowid), "text": msg})
        self.state["last_rowid"] = self.last_rowid
        return out

    # -- outbound -------------------------------------------------------
    def send(self, text: str) -> dict[str, Any]:
        if not self.configured:
            return {"sent": False, "error": "iMessage self-chat not configured"}
        body = (text or "").strip()
        if not body:
            return {"sent": False, "error": "empty"}
        self._sent[_digest(body)] = time.time()
        try:
            with appleevents_lock("messages"):
                proc = subprocess.run(
                    ["osascript", "-", self.send_to, body, self.service],
                    input=_SEND_SCRIPT, capture_output=True, text=True, timeout=30,
                )
        except subprocess.TimeoutExpired:
            return {"sent": False, "uncertain": True, "error": "Messages did not answer in 30 s"}
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()[-300:]
            if "-1743" in err or "not allowed" in err.lower():
                err = "Automation permission for Messages is needed (System Settings → Privacy & Security → Automation)"
            self.error = err
            return {"sent": False, "error": err}
        return {"sent": True, "to": self.send_to}
