"""Discord adapter.

Listens for direct messages (and channel messages that @mention the bot)
from an allowlist of Discord user IDs, runs them through the agent, and
replies in the same channel. The bot account is created at
<https://discord.com/developers/applications> — paste its token in the
DISCORD_BOT_TOKEN env var. To restrict who can talk to it (recommended
for a robot bot), set DISCORD_ALLOWED_USER_IDS to a comma-separated list
of numeric Discord user IDs.

Required env vars:
    DISCORD_BOT_TOKEN          — bot token from the Developer Portal
    DISCORD_ALLOWED_USER_IDS   — optional, comma-separated user IDs

Required Discord intents (toggle in the Developer Portal under "Bot"):
    Server Members Intent      — off (we don't need member events)
    Message Content Intent     — ON (otherwise message.content is empty)
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, Callable


def _parse_allowed_users() -> set[int]:
    raw = os.environ.get("DISCORD_ALLOWED_USER_IDS", "").strip()
    if not raw:
        return set()
    out: set[int] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.add(int(token))
        except ValueError:
            continue
    return out


class DiscordBridge:
    """Run-and-stop wrapper around a discord.py Client.

    Construction does NOT connect. Call `start()` to begin running on a
    background asyncio loop in a daemon thread; `stop()` to close cleanly.
    The `handler` callback receives the raw user text and must return a
    string reply. It's called from a worker thread so it can do blocking
    work (LLM inference) without blocking the Discord client's loop.
    """

    def __init__(self, handler: Callable[[str], str],
                 llm_lock: threading.Lock | None = None,
                 token: str | None = None,
                 allowed_users: set[int] | None = None,
                 bus: Any = None,
                 admin_ids: set[str] | None = None) -> None:
        try:
            import discord  # noqa: F401 — surface ImportError up front
        except ImportError as exc:
            raise RuntimeError(f"discord.py missing — pip install 'discord.py>=2.4' ({exc})")

        self._handler = handler
        self._llm_lock = llm_lock
        # Instance-folder first: token/allowlist passed by the in-process
        # activator (from <instance>/credentials/); env is a legacy fallback.
        self._allowed = allowed_users if allowed_users is not None else _parse_allowed_users()
        self._bus = bus
        # The owner's certified user ids (the only admin). Others get
        # conversation-only access — no slash, no tier-gated actions.
        self._admin = {str(a) for a in (admin_ids or set())}
        self._awaiting: dict[str, str] = {}   # recipient → pending approval id
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._token = (token or os.environ.get("DISCORD_BOT_TOKEN", "")).strip()
        if not self._token:
            raise RuntimeError(
                "DISCORD_BOT_TOKEN required — save it with set_credential "
                "(instance credential store) or export it (legacy)")

    # ----- lifecycle -----
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="discord-bridge")
        self._thread.start()
        # Register so the agent's send_message tool can find us.
        from .. import register_bridge
        register_bridge("discord", self)

    def stop(self) -> None:
        from .. import deregister_bridge
        deregister_bridge("discord")
        if self._client is None or self._loop is None:
            return
        coro = self._client.close()
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            future.result(timeout=10)
        except Exception:
            pass

    # ----- outbound: agent-initiated messages -----
    def send(self, recipient: str, text: str) -> dict[str, Any]:
        """Send `text` to a Discord user ID (DM) or channel ID.

        `recipient` is the numeric ID as a string. If it's a user ID we
        open/reuse a DM; if it's a channel ID we post in that channel.
        Returns {sent, channel_id, message_id} on success or
        {sent: False, error: "..."} on failure.
        """
        if self._client is None or self._loop is None:
            return {"sent": False, "error": "discord bridge not connected"}
        try:
            recipient_id = int(recipient)
        except (TypeError, ValueError):
            return {"sent": False, "error": f"recipient must be a numeric Discord ID, got {recipient!r}"}

        async def _do_send() -> dict[str, Any]:
            target: Any = self._client.get_user(recipient_id) or self._client.get_channel(recipient_id)
            if target is None:
                # User not in cache; try to fetch from API.
                try:
                    target = await self._client.fetch_user(recipient_id)
                except Exception as exc:
                    return {"sent": False, "error": f"unknown user/channel {recipient_id}: {exc}"}
            sender = target
            # For users, sending requires opening a DM channel first.
            if hasattr(target, "create_dm"):
                sender = await target.create_dm()
            for i in range(0, len(text), 1900):
                msg = await sender.send(text[i : i + 1900])
            return {"sent": True, "channel_id": str(sender.id), "message_id": str(msg.id)}

        try:
            fut = asyncio.run_coroutine_threadsafe(_do_send(), self._loop)
            return fut.result(timeout=15)
        except Exception as exc:
            return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}

    # ----- internals -----
    def _run(self) -> None:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True

        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready() -> None:
            print(f"[discord] connected as {client.user}", flush=True)
            if self._allowed:
                print(f"[discord] allowlist: {len(self._allowed)} user(s)", flush=True)
            else:
                print("[discord] no allowlist — accepting all DMs (set DISCORD_ALLOWED_USER_IDS to restrict)", flush=True)

        @client.event
        async def on_message(message: Any) -> None:
            if message.author == client.user:
                return
            uid = int(getattr(message.author, "id", 0))
            if self._allowed and uid not in self._allowed:
                return

            is_dm = isinstance(message.channel, discord.DMChannel)
            mentioned = client.user in getattr(message, "mentions", [])
            if not (is_dm or mentioned):
                return

            content = (message.content or "").strip()
            if mentioned:
                # Strip the @mention prefix
                content = content.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "").strip()
            if not content:
                return

            # One session per Discord channel — DMs and shared channels each
            # keep their own rolling history so two users in two channels
            # don't see each other's context.
            channel_id = int(getattr(message.channel, "id", 0))
            session_key = f"discord:{channel_id}" if channel_id else f"discord:user:{uid}"

            async with message.channel.typing():
                # Run the (blocking) LLM call in a thread so we don't block the discord loop.
                reply = await asyncio.to_thread(self._safe_handle, content, session_key)
            if reply:
                # Discord caps messages at 2000 chars
                for i in range(0, len(reply), 1900):
                    await message.channel.send(reply[i : i + 1900])

        try:
            client.run(self._token, log_handler=None)
        except Exception as exc:
            print(f"[discord] client.run failed: {exc}", flush=True)

    def _safe_handle(self, text: str, session_key: str | None = None) -> str:
        try:
            if self._llm_lock is not None:
                with self._llm_lock:
                    return self._call_handler(text, session_key) or ""
            return self._call_handler(text, session_key) or ""
        except Exception as exc:
            return f"(agent error: {type(exc).__name__}: {exc})"

    def _call_handler(self, text: str, session_key: str | None) -> str:
        try:
            return self._handler(text, session_key=session_key) or ""
        except TypeError:
            return self._handler(text) or ""
