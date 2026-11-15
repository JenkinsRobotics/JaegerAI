"""Telegram transport for Jaeger's own bot (Bot API over HTTPS, long polling).

Locked to one private chat. Until paired, the only accepted message is
``/pair <code>`` (code from ``jaeger channels pair telegram`` or Settings →
Channels), sent from a private chat; the first valid code binds that chat id
and the code is burned. Everyone else is ignored silently.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import save_config

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4000


class TelegramBot:
    name = "telegram"

    def __init__(self, cfg: dict[str, Any], full_cfg: dict[str, Any], token: str | None,
                 state: dict[str, Any]) -> None:
        self.cfg = cfg
        self.full_cfg = full_cfg
        self._token = token
        self.state = state
        self.offset = int(state.get("offset") or 0)
        self.error: str | None = None
        self.bot_username: str | None = state.get("bot_username")

    @property
    def configured(self) -> bool:
        return bool(self._token)

    @property
    def chat_id(self) -> int | None:
        value = self.cfg.get("allowed_chat_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "paired": self.chat_id is not None,
            "bot_username": self.bot_username,
            "error": self.error,
            "pairing_pending": bool(self.cfg.get("pairing_code")) and self.chat_id is None,
        }

    # -- HTTP -----------------------------------------------------------
    def _call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 40) -> Any:
        url = API.format(token=self._token, method=method)
        data = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:  # noqa: BLE001
                payload = {"ok": False, "description": f"HTTP {exc.code}"}
        if not payload.get("ok"):
            # Never echo the URL (it contains the token).
            raise RuntimeError(str(payload.get("description") or "Telegram API error"))
        return payload.get("result")

    def hello(self) -> None:
        me = self._call("getMe", timeout=15)
        self.bot_username = me.get("username")
        self.state["bot_username"] = self.bot_username

    # -- inbound --------------------------------------------------------
    def poll(self) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        try:
            if not self.bot_username:
                self.hello()
            updates = self._call("getUpdates", {"offset": self.offset or None, "timeout": 25,
                                               "allowed_updates": json.dumps(["message"])}, timeout=40)
            self.error = None
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)[:300]
            time.sleep(5)
            return []
        out: list[dict[str, Any]] = []
        for upd in updates or []:
            self.offset = max(self.offset, int(upd.get("update_id", 0)) + 1)
            msg = upd.get("message") or {}
            chat = msg.get("chat") or {}
            text = (msg.get("text") or msg.get("caption") or "").strip()
            if chat.get("type") != "private" or not text:
                continue
            cid = int(chat.get("id"))
            if self.chat_id is None:
                self._try_pair(cid, text)
                continue
            if cid != self.chat_id:
                continue  # locked to the owner's chat
            if text.split()[0].lower() in {"/start", "/pair"}:
                self.send("Already paired with you. Just talk to me here.")
                continue
            out.append({"id": str(msg.get("message_id")), "text": text})
        self.state["offset"] = self.offset
        return out

    def _try_pair(self, chat_id: int, text: str) -> None:
        parts = text.split()
        code = self.cfg.get("pairing_code")
        expires = float(self.cfg.get("pairing_expires_at") or 0)
        if len(parts) == 2 and parts[0].lower() in {"/pair", "/start"} and code \
                and parts[1] == code and time.time() < expires:
            self.cfg["allowed_chat_id"] = chat_id
            self.cfg["pairing_code"] = None
            self.cfg["pairing_expires_at"] = None
            self.full_cfg["telegram"] = self.cfg
            save_config(self.full_cfg)
            self.send("Paired. This chat now reaches Jaeger, and only this chat.")

    # -- outbound -------------------------------------------------------
    def send(self, text: str) -> dict[str, Any]:
        if not self.configured or self.chat_id is None:
            return {"sent": False, "error": "Telegram not paired"}
        body = (text or "").strip()
        if not body:
            return {"sent": False, "error": "empty"}
        try:
            for start in range(0, len(body), MAX_LEN):
                self._call("sendMessage", {"chat_id": self.chat_id, "text": body[start:start + MAX_LEN],
                                           "disable_web_page_preview": "true"}, timeout=20)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)[:300]
            return {"sent": False, "error": self.error}
        return {"sent": True, "to": "telegram"}

    def typing(self) -> None:
        if self.configured and self.chat_id is not None:
            try:
                self._call("sendChatAction", {"chat_id": self.chat_id, "action": "typing"}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
