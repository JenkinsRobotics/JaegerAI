"""Modular in-process multi-channel adapters (Telegram, Discord, Slack, iMessage)
and async ingress supervisor for jaeger-channels.

Design invariants:
- Pure Python stdlib (zero external daemons, zero extra pip dependencies).
- Fail-closed validation: fixed endpoints, no redirects, no ambient proxy env vars,
  and receipts never persist raw response bodies or exception strings containing tokens.
- User-owned config in `<state_dir>/channels.json` + optional env vars (never hardcoded).
- Outbound delivery always remains gated by `ChannelHub` owner approvals & secret scrubbing.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from .discord_guard import AmbientRoomBuffer, BotLoopGuard, is_mentioned
from .webhook import _NoRedirect, _validate_token, _validate_webhook_url

__all__ = [
    "ChannelConfigError",
    "ChannelConfigStore",
    "ChannelIngressSupervisor",
    "DiscordChannelPoller",
    "SlackChannelPoller",
    "TelegramPoller",
    "build_discord_adapter",
    "build_imessage_adapter",
    "build_slack_adapter",
    "build_telegram_adapter",
]

_TELEGRAM_TOKEN_RE = re.compile(r"^[0-9]{5,18}:[A-Za-z0-9_-]{16,120}$")
_DIGITS_RE = re.compile(r"^[0-9]{5,30}$")
_IMESSAGE_RECIPIENT_RE = re.compile(r"^(\+[0-9]{7,16}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})$")
_DEFAULT_TIMEOUT_S = 10.0


class ChannelConfigError(ValueError):
    """Raised when a channel adapter configuration is invalid (fail closed)."""


def _safe_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "jaeger-channels/0.2",
        **(dict(headers or {})),
    }
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    with opener.open(req, timeout=timeout_s) as resp:
        status = int(resp.status)
        raw = resp.read(65_536)
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
        except json.JSONDecodeError:
            parsed = {}
        return status, parsed if isinstance(parsed, dict) else {}


def build_telegram_adapter(
    bot_token: str,
    *,
    api_base: str = "https://api.telegram.org",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Callable[[str, str], dict[str, Any]]:
    """Build an outbound Telegram Bot API adapter (`sendMessage`)."""
    token = (bot_token or "").strip()
    if not _TELEGRAM_TOKEN_RE.match(token):
        raise ChannelConfigError("invalid Telegram bot token format")
    base = _validate_webhook_url(api_base.rstrip("/"))
    endpoint = f"{base}/bot{token}/sendMessage"
    opener = _safe_opener()
    timeout = max(1.0, min(float(timeout_s), 30.0))

    def adapter(recipient: str, body: str) -> dict[str, Any]:
        chat_id = (recipient or "").strip()
        if not chat_id or len(chat_id) > 128:
            return {"delivered": False, "error": "invalid_chat_id"}
        try:
            status, parsed = _post_json(
                opener,
                endpoint,
                {"chat_id": chat_id, "text": (body or "")[:4096]},
                timeout_s=timeout,
            )
        except urllib.error.HTTPError as exc:
            return {"delivered": False, "http_status": int(exc.code), "error": "http_error"}
        except (urllib.error.URLError, OSError):
            return {"delivered": False, "error": "request_failed"}
        except Exception:  # noqa: BLE001
            return {"delivered": False, "error": "adapter_error"}
        if 200 <= status < 300 and parsed.get("ok") is True:
            msg_id = (parsed.get("result") or {}).get("message_id") if isinstance(parsed.get("result"), dict) else None
            return {"delivered": True, "http_status": status, **({"message_id": msg_id} if msg_id is not None else {})}
        return {"delivered": False, "http_status": status, "error": "telegram_rejected"}

    return adapter


def build_discord_adapter(
    credential: str,
    *,
    mode: str = "webhook",
    api_base: str = "https://discord.com/api/v10",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Callable[[str, str], dict[str, Any]]:
    """Build an outbound Discord adapter (incoming webhook URL or Bot API token)."""
    opener = _safe_opener()
    timeout = max(1.0, min(float(timeout_s), 30.0))

    if mode == "webhook":
        endpoint = _validate_webhook_url((credential or "").strip())

        def webhook_adapter(recipient: str, body: str) -> dict[str, Any]:
            prefix = f"[{recipient}] " if recipient and recipient not in ("owner", "default") else ""
            text = (prefix + (body or ""))[:2000]
            try:
                status, _ = _post_json(opener, endpoint, {"content": text}, timeout_s=timeout)
            except urllib.error.HTTPError as exc:
                return {"delivered": False, "http_status": int(exc.code), "error": "http_error"}
            except (urllib.error.URLError, OSError):
                return {"delivered": False, "error": "request_failed"}
            except Exception:  # noqa: BLE001
                return {"delivered": False, "error": "adapter_error"}
            return {"delivered": 200 <= status < 300, "http_status": status}

        return webhook_adapter

    if mode == "bot":
        token = _validate_token((credential or "").strip())
        base = _validate_webhook_url(api_base.rstrip("/"))

        def bot_adapter(recipient: str, body: str) -> dict[str, Any]:
            channel_id = (recipient or "").strip()
            if not _DIGITS_RE.match(channel_id):
                return {"delivered": False, "error": "discord_channel_id_must_be_numeric"}
            endpoint = f"{base}/channels/{channel_id}/messages"
            try:
                status, parsed = _post_json(
                    opener,
                    endpoint,
                    {"content": (body or "")[:2000]},
                    headers={"Authorization": f"Bot {token}"},
                    timeout_s=timeout,
                )
            except urllib.error.HTTPError as exc:
                return {"delivered": False, "http_status": int(exc.code), "error": "http_error"}
            except (urllib.error.URLError, OSError):
                return {"delivered": False, "error": "request_failed"}
            except Exception:  # noqa: BLE001
                return {"delivered": False, "error": "adapter_error"}
            if 200 <= status < 300:
                return {"delivered": True, "http_status": status, **({"message_id": parsed.get("id")} if parsed.get("id") else {})}
            return {"delivered": False, "http_status": status, "error": "discord_rejected"}

        return bot_adapter

    raise ChannelConfigError(f"unsupported Discord mode: {mode!r}")


def build_slack_adapter(
    credential: str,
    *,
    mode: str = "webhook",
    api_base: str = "https://slack.com/api",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Callable[[str, str], dict[str, Any]]:
    """Build an outbound Slack adapter (incoming webhook URL or Web API Bot token)."""
    opener = _safe_opener()
    timeout = max(1.0, min(float(timeout_s), 30.0))

    if mode == "webhook":
        endpoint = _validate_webhook_url((credential or "").strip())

        def webhook_adapter(_recipient: str, body: str) -> dict[str, Any]:
            try:
                status, _ = _post_json(opener, endpoint, {"text": (body or "")[:4000]}, timeout_s=timeout)
            except urllib.error.HTTPError as exc:
                return {"delivered": False, "http_status": int(exc.code), "error": "http_error"}
            except (urllib.error.URLError, OSError):
                return {"delivered": False, "error": "request_failed"}
            except Exception:  # noqa: BLE001
                return {"delivered": False, "error": "adapter_error"}
            return {"delivered": 200 <= status < 300, "http_status": status}

        return webhook_adapter

    if mode == "bot":
        token = _validate_token((credential or "").strip())
        base = _validate_webhook_url(api_base.rstrip("/"))
        endpoint = f"{base}/chat.postMessage"

        def bot_adapter(recipient: str, body: str) -> dict[str, Any]:
            channel = (recipient or "").strip()
            if not channel or len(channel) > 128:
                return {"delivered": False, "error": "invalid_slack_channel"}
            try:
                status, parsed = _post_json(
                    opener,
                    endpoint,
                    {"channel": channel, "text": (body or "")[:4000]},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout_s=timeout,
                )
            except urllib.error.HTTPError as exc:
                return {"delivered": False, "http_status": int(exc.code), "error": "http_error"}
            except (urllib.error.URLError, OSError):
                return {"delivered": False, "error": "request_failed"}
            except Exception:  # noqa: BLE001
                return {"delivered": False, "error": "adapter_error"}
            if 200 <= status < 300 and parsed.get("ok") is True:
                return {"delivered": True, "http_status": status}
            return {"delivered": False, "http_status": status, "error": "slack_rejected"}

        return bot_adapter

    raise ChannelConfigError(f"unsupported Slack mode: {mode!r}")


def build_imessage_adapter(*, timeout_s: float = 15.0) -> Callable[[str, str], dict[str, Any]]:
    """Build a macOS Messages.app outbound adapter (fail-closed on non-Darwin or invalid handle)."""
    timeout = max(2.0, min(float(timeout_s), 30.0))

    def _as_escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", "\\n")

    def adapter(recipient: str, body: str) -> dict[str, Any]:
        if platform.system() != "Darwin":
            return {"delivered": False, "error": "imessage_requires_macos"}
        handle = (recipient or "").strip()
        if not _IMESSAGE_RECIPIENT_RE.match(handle):
            return {"delivered": False, "error": "invalid_imessage_recipient"}
        script = (
            'tell application "Messages"\n'
            '  set targetService to 1st account whose service type = iMessage\n'
            f'  set targetBuddy to participant "{_as_escape(handle)}" of targetService\n'
            f'  send "{_as_escape((body or "")[:2000])}" to targetBuddy\n'
            "end tell\n"
        )
        try:
            proc = subprocess.run(
                ["/usr/bin/osascript", "-"],
                input=script,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"delivered": False, "error": "osascript_failed"}
        if proc.returncode == 0:
            return {"delivered": True, "transport": "imessage"}
        return {"delivered": False, "error": "messages_app_rejected"}

    return adapter


class ChannelConfigStore:
    """Owner-configured channel settings persisted in `<state_dir>/channels.json`."""

    def __init__(self, state_dir: Path) -> None:
        self._path = Path(state_dir).expanduser().resolve() / "channels.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self._path.is_file():
            try:
                parsed = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    data = parsed
            except (OSError, json.JSONDecodeError):
                data = {}
        # Layer explicit environment overrides cleanly (without mutating disk).
        tg_token = (os.environ.get("JAEGER_TELEGRAM_BOT_TOKEN") or "").strip()
        if tg_token:
            tg = dict(data.get("telegram") or {})
            tg["bot_token"] = tg_token
            tg.setdefault("enabled", True)
            env_chats = (os.environ.get("JAEGER_TELEGRAM_ALLOWED_CHAT_IDS") or "").strip()
            if env_chats:
                tg["allowed_chat_ids"] = [c.strip() for c in env_chats.split(",") if c.strip()]
            data["telegram"] = tg
        dc_hook = (os.environ.get("JAEGER_DISCORD_WEBHOOK_URL") or "").strip()
        if dc_hook:
            dc = dict(data.get("discord") or {})
            dc["webhook_url"] = dc_hook
            dc.setdefault("enabled", True)
            data["discord"] = dc
        sl_hook = (os.environ.get("JAEGER_SLACK_WEBHOOK_URL") or "").strip()
        if sl_hook:
            sl = dict(data.get("slack") or {})
            sl["webhook_url"] = sl_hook
            sl.setdefault("enabled", True)
            data["slack"] = sl
        if (os.environ.get("JAEGER_IMESSAGE_ENABLED") or "").strip().lower() in ("1", "true", "yes"):
            im = dict(data.get("imessage") or {})
            im["enabled"] = True
            data["imessage"] = im
        return data

    def public_summary(self) -> dict[str, Any]:
        """Return a redacted summary safe for API/UI display (never exposes tokens/URLs)."""
        cfg = self.load()
        out: dict[str, Any] = {}
        for name in ("telegram", "discord", "slack", "imessage", "webhook", "email"):
            sec = cfg.get(name) if isinstance(cfg.get(name), Mapping) else {}
            out[name] = {
                "enabled": bool(sec.get("enabled", False)),
                "configured": bool(
                    sec.get("bot_token") or sec.get("webhook_url") or sec.get("enabled")
                ),
                "allowed_senders_count": len(sec.get("allowed_chat_ids") or sec.get("allowed_senders") or ()),
                "auto_reply_owner": bool(sec.get("auto_reply_owner", False)),
            }
        return out


InboundCallback = Callable[[str, str, str, str, str, bool], Awaitable[None] | None]


class TelegramPoller:
    """In-process asyncio long-poller for Telegram Bot API `getUpdates`."""

    def __init__(
        self,
        bot_token: str,
        *,
        on_message: InboundCallback,
        allowed_chat_ids: set[str] | None = None,
        auto_reply_owner: bool = False,
        api_base: str = "https://api.telegram.org",
        poll_interval_s: float = 2.0,
    ) -> None:
        token = (bot_token or "").strip()
        if not _TELEGRAM_TOKEN_RE.match(token):
            raise ChannelConfigError("invalid Telegram bot token format")
        self._endpoint = f"{_validate_webhook_url(api_base.rstrip('/'))}/bot{token}/getUpdates"
        self._on_message = on_message
        self._allowed = {str(c).strip() for c in (allowed_chat_ids or set()) if str(c).strip()}
        self._auto_reply = bool(auto_reply_owner)
        self._poll_interval_s = max(0.2, float(poll_interval_s))
        self._opener = _safe_opener()
        self._offset = 0

    def fetch_updates_sync(self, *, timeout_s: int = 10) -> list[dict[str, Any]]:
        status, parsed = _post_json(
            self._opener,
            self._endpoint,
            {"offset": self._offset, "timeout": max(0, min(int(timeout_s), 25)), "allowed_updates": ["message"]},
            timeout_s=max(5.0, float(timeout_s) + 5.0),
        )
        if not (200 <= status < 300 and parsed.get("ok") is True):
            return []
        raw_list = parsed.get("result")
        return [u for u in raw_list if isinstance(u, dict)] if isinstance(raw_list, list) else []

    async def poll_once(self, *, timeout_s: int = 0) -> int:
        updates = await asyncio.to_thread(self.fetch_updates_sync, timeout_s=timeout_s)
        processed = 0
        for upd in updates:
            uid = upd.get("update_id")
            if isinstance(uid, int):
                self._offset = max(self._offset, uid + 1)
            msg = upd.get("message")
            if not isinstance(msg, dict):
                continue
            text = str(msg.get("text") or "").strip()
            if not text:
                continue
            chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
            chat_id = str(chat.get("id") or "").strip()
            if not chat_id:
                continue
            if self._allowed and chat_id not in self._allowed:
                continue
            sender_obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}
            sender = str(sender_obj.get("username") or sender_obj.get("id") or chat_id)
            msg_id = str(msg.get("message_id") or uid or "")
            if not msg_id:
                continue
            res = self._on_message("telegram", chat_id, msg_id, sender, text, self._auto_reply)
            if asyncio.iscoroutine(res):
                await res
            processed += 1
        return processed

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once(timeout_s=15)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(self._poll_interval_s)


def _get_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> tuple[int, Any]:
    req_headers = {
        "Accept": "application/json",
        "User-Agent": "jaeger-channels/0.2",
        **(dict(headers or {})),
    }
    req = urllib.request.Request(url, headers=req_headers, method="GET")
    with opener.open(req, timeout=timeout_s) as resp:
        status = int(resp.status)
        raw = resp.read(200_000)
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace")) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return status, parsed


class DiscordChannelPoller:
    """In-process asyncio poller for allowlisted Discord Bot API text channels."""

    def __init__(
        self,
        bot_token: str,
        channel_ids: list[str],
        *,
        on_message: InboundCallback,
        allowed_user_ids: set[str] | None = None,
        auto_reply_owner: bool = False,
        api_base: str = "https://discord.com/api/v10",
        poll_interval_s: float = 4.0,
        mention_tokens: list[str] | None = None,
        ambient_buffer: AmbientRoomBuffer | None = None,
        loop_guard: BotLoopGuard | None = None,
    ) -> None:
        self._token = _validate_token((bot_token or "").strip())
        self._base = _validate_webhook_url(api_base.rstrip("/"))
        valid_cids = [str(c).strip() for c in channel_ids if _DIGITS_RE.match(str(c).strip())]
        if not valid_cids:
            raise ChannelConfigError("DiscordChannelPoller requires at least one numeric channel_id")
        self._channels = valid_cids
        self._on_message = on_message
        self._allowed_users = {str(u).strip() for u in (allowed_user_ids or set()) if str(u).strip()}
        self._auto_reply = bool(auto_reply_owner)
        self._poll_interval_s = max(0.5, float(poll_interval_s))
        self._mention_tokens = [t.strip() for t in (mention_tokens or []) if t and t.strip()]
        self._ambient = ambient_buffer or AmbientRoomBuffer()
        self._loop_guard = loop_guard or BotLoopGuard()
        self._opener = _safe_opener()
        self._last_id: dict[str, str] = {}

    @property
    def ambient_buffer(self) -> AmbientRoomBuffer:
        return self._ambient

    def _fetch_channel_sync(self, channel_id: str) -> list[dict[str, Any]]:
        qs = f"?limit=10&after={self._last_id[channel_id]}" if channel_id in self._last_id else "?limit=10"
        url = f"{self._base}/channels/{channel_id}/messages{qs}"
        status, parsed = _get_json(self._opener, url, headers={"Authorization": f"Bot {self._token}"}, timeout_s=10.0)
        if not (200 <= status < 300 and isinstance(parsed, list)):
            return []
        return [m for m in reversed(parsed) if isinstance(m, dict)]

    async def poll_once(self) -> int:
        processed = 0
        for cid in self._channels:
            msgs = await asyncio.to_thread(self._fetch_channel_sync, cid)
            for msg in msgs:
                mid = str(msg.get("id") or "").strip()
                if not mid:
                    continue
                self._last_id[cid] = mid
                author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
                is_bot = bool(author.get("bot"))
                if is_bot:
                    self._loop_guard.allow_inbound(cid, is_bot_author=True)
                    continue
                uid = str(author.get("id") or "").strip()
                if self._allowed_users and uid not in self._allowed_users:
                    continue
                text = str(msg.get("content") or "").strip()
                if not text:
                    continue
                sender = str(author.get("username") or uid or "discord_user")
                if self._mention_tokens and not is_mentioned(text, self._mention_tokens):
                    self._ambient.record(cid, sender, text)
                    continue
                allowed, _reason = self._loop_guard.allow_inbound(cid, is_bot_author=False)
                if not allowed:
                    self._ambient.record(cid, sender, text)
                    continue
                context_prefix = self._ambient.format_context(cid, limit=8)
                delivered_text = f"{context_prefix}\n\n{text}" if context_prefix else text
                res = self._on_message("discord", cid, mid, sender, delivered_text, self._auto_reply)
                if asyncio.iscoroutine(res):
                    await res
                self._loop_guard.record_reply(cid)
                processed += 1
        return processed

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(self._poll_interval_s)


class SlackChannelPoller:
    """In-process asyncio poller for allowlisted Slack Bot API channels (`conversations.history`)."""

    def __init__(
        self,
        bot_token: str,
        channel_ids: list[str],
        *,
        on_message: InboundCallback,
        allowed_user_ids: set[str] | None = None,
        auto_reply_owner: bool = False,
        api_base: str = "https://slack.com/api",
        poll_interval_s: float = 4.0,
    ) -> None:
        self._token = _validate_token((bot_token or "").strip())
        self._base = _validate_webhook_url(api_base.rstrip("/"))
        valid_cids = [str(c).strip() for c in channel_ids if str(c).strip() and len(str(c).strip()) <= 64]
        if not valid_cids:
            raise ChannelConfigError("SlackChannelPoller requires at least one channel_id")
        self._channels = valid_cids
        self._on_message = on_message
        self._allowed_users = {str(u).strip() for u in (allowed_user_ids or set()) if str(u).strip()}
        self._auto_reply = bool(auto_reply_owner)
        self._poll_interval_s = max(0.5, float(poll_interval_s))
        self._opener = _safe_opener()
        self._oldest_ts: dict[str, str] = {}

    def _fetch_channel_sync(self, channel_id: str) -> list[dict[str, Any]]:
        import urllib.parse

        params: dict[str, Any] = {"channel": channel_id, "limit": 10}
        if channel_id in self._oldest_ts:
            params["oldest"] = self._oldest_ts[channel_id]
        url = f"{self._base}/conversations.history?{urllib.parse.urlencode(params)}"
        status, parsed = _get_json(self._opener, url, headers={"Authorization": f"Bearer {self._token}"}, timeout_s=10.0)
        if not (200 <= status < 300 and isinstance(parsed, dict) and parsed.get("ok") is True):
            return []
        raw = parsed.get("messages")
        if not isinstance(raw, list):
            return []
        valid = [m for m in raw if isinstance(m, dict)]
        valid.sort(key=lambda m: str(m.get("ts") or ""))
        return valid

    async def poll_once(self) -> int:
        processed = 0
        for cid in self._channels:
            msgs = await asyncio.to_thread(self._fetch_channel_sync, cid)
            for msg in msgs:
                ts = str(msg.get("ts") or "").strip()
                if not ts:
                    continue
                if cid in self._oldest_ts and ts <= self._oldest_ts[cid]:
                    continue
                self._oldest_ts[cid] = ts
                if msg.get("bot_id") or msg.get("subtype") == "bot_message":
                    continue
                uid = str(msg.get("user") or "").strip()
                if self._allowed_users and uid not in self._allowed_users:
                    continue
                text = str(msg.get("text") or "").strip()
                if not text:
                    continue
                res = self._on_message("slack", cid, ts, uid or "slack_user", text, self._auto_reply)
                if asyncio.iscoroutine(res):
                    await res
                processed += 1
        return processed

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(self._poll_interval_s)


class ChannelIngressSupervisor:
    """Supervises zero-daemon in-process async channel pollers inside Gateway."""

    def __init__(self) -> None:
        self._pollers: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def register_poller(self, name: str, poller: Any) -> None:
        self._pollers[name] = poller

    def start(self) -> list[str]:
        started: list[str] = []
        for name, poller in self._pollers.items():
            existing = self._tasks.get(name)
            if existing is not None and not existing.done():
                continue
            self._tasks[name] = asyncio.create_task(poller.run_forever(), name=f"jaeger-channel-{name}")
            started.append(name)
        return started

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass

    def status(self) -> dict[str, Any]:
        return {
            "pollers": {
                name: {"running": bool(self._tasks.get(name) and not self._tasks[name].done())}
                for name in sorted(self._pollers.keys())
            }
        }
