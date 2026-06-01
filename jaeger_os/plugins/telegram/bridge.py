"""Telegram adapter.

Listens for incoming messages from an allowlist of Telegram chat IDs,
runs them through the agent, and replies in the same chat. The bot is
created by talking to @BotFather on Telegram — paste the resulting token
in TELEGRAM_BOT_TOKEN. To restrict who can talk to it, set
TELEGRAM_ALLOWED_CHAT_IDS to a comma-separated list of numeric chat IDs
(use `getUpdates` or @userinfobot to find them).

Required env vars:
    TELEGRAM_BOT_TOKEN          — bot token from @BotFather
    TELEGRAM_ALLOWED_CHAT_IDS   — optional, comma-separated chat IDs

Uses long-polling so no public URL / webhook is needed — works behind a
home router with no port forwarding. The poll loop holds an HTTP request
open against Telegram's servers; the moment a message arrives the server
returns it, so there's no "scheduler" interval — replies start as soon as
the LLM finishes generating. The bridge also logs each receive/reply so
you can verify the round-trip in the gateway console.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any, Callable


def _parse_allowed_chats() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
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


class TelegramBridge:
    """Same shape as DiscordBridge: handler(text) → reply text.

    Construction does NOT connect. `start()` spawns a daemon thread that
    owns the asyncio loop; `stop()` cancels the long-poll cleanly.
    `send(recipient, text)` works after start() — it serializes the call
    through the same asyncio loop.
    """

    def __init__(self, handler: Callable[[str], str], llm_lock: threading.Lock | None = None) -> None:
        try:
            from telegram.ext import Application  # noqa: F401 — surface ImportError up front
        except ImportError as exc:
            raise RuntimeError(f"python-telegram-bot missing — pip install 'python-telegram-bot>=20' ({exc})")

        self._handler = handler
        self._llm_lock = llm_lock
        self._allowed = _parse_allowed_chats()
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not self._token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN env var is required")

        self._app: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    # ----- lifecycle -----
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="telegram-bridge")
        self._thread.start()
        # Wait briefly so register_bridge happens after the loop exists; the
        # send() call needs `self._loop` to be set.
        self._ready.wait(timeout=15)
        from .. import register_bridge
        register_bridge("telegram", self)

    def stop(self) -> None:
        from .. import deregister_bridge
        deregister_bridge("telegram")
        if self._app is None or self._loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._app.stop(), self._loop)
            fut.result(timeout=10)
        except Exception:
            pass

    # ----- outbound: agent-initiated messages -----
    def send(self, recipient: str, text: str) -> dict[str, Any]:
        """Send `text` to a Telegram chat ID (numeric, as a string)."""
        if self._app is None or self._loop is None:
            return {"sent": False, "error": "telegram bridge not connected"}
        try:
            chat_id = int(recipient)
        except (TypeError, ValueError):
            return {"sent": False, "error": f"recipient must be a numeric chat ID, got {recipient!r}"}

        async def _do_send() -> Any:
            return await self._app.bot.send_message(chat_id=chat_id, text=text)

        try:
            fut = asyncio.run_coroutine_threadsafe(_do_send(), self._loop)
            msg = fut.result(timeout=15)
            return {"sent": True, "chat_id": str(chat_id), "message_id": str(getattr(msg, "message_id", "?"))}
        except Exception as exc:
            return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}

    # ----- internals -----
    def _run(self) -> None:
        from telegram import Update
        from telegram.ext import Application, MessageHandler, filters

        async def _bootstrap() -> None:
            app = Application.builder().token(self._token).build()
            self._app = app

            async def on_message(update: Update, _ctx: Any) -> None:
                msg = update.effective_message
                if not msg or not msg.text:
                    return
                chat_id = update.effective_chat.id if update.effective_chat else 0
                if self._allowed and chat_id not in self._allowed:
                    print(f"[telegram] dropped message from non-allowlisted chat_id={chat_id}", flush=True)
                    return
                preview = msg.text.strip()
                short = preview if len(preview) <= 60 else preview[:57] + "..."
                print(f"[telegram] ← chat={chat_id} {short!r}", flush=True)
                # Show a "typing…" indicator while the LLM works so the
                # human can see we're alive even on a slow turn.
                async def _keep_typing():
                    try:
                        while True:
                            try:
                                await msg.chat.send_chat_action(action="typing")
                            except Exception:
                                pass
                            await asyncio.sleep(4.0)
                    except asyncio.CancelledError:
                        return

                typing_task = asyncio.create_task(_keep_typing())
                started = time.perf_counter()
                try:
                    reply = await asyncio.to_thread(
                        self._safe_handle, preview, f"telegram:{chat_id}"
                    )
                finally:
                    typing_task.cancel()
                elapsed = time.perf_counter() - started
                if reply:
                    for i in range(0, len(reply), 4000):
                        await msg.reply_text(reply[i : i + 4000])
                    print(f"[telegram] → chat={chat_id} ({len(reply)} chars in {elapsed:.1f}s)", flush=True)
                else:
                    print(f"[telegram] → chat={chat_id} (empty reply after {elapsed:.1f}s)", flush=True)

            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

            await app.initialize()
            await app.start()
            # poll_interval=0 + timeout=25 = long-poll: Telegram holds the
            # request open until a message arrives, then returns instantly.
            # No "tick rate" between messages — perceived delivery latency is
            # network-bound (sub-second) and reply latency is bounded only by
            # LLM inference time.
            await app.updater.start_polling(
                poll_interval=0.0,
                timeout=25,
                allowed_updates=Update.ALL_TYPES,
            )
            print(f"[telegram] connected (long-poll, instant delivery); allowlist: "
                  f"{sorted(self._allowed) if self._allowed else 'OPEN (set TELEGRAM_ALLOWED_CHAT_IDS to restrict)'}",
                  flush=True)
            self._ready.set()

            # Park forever until stop() is called.
            try:
                await asyncio.Event().wait()
            finally:
                try:
                    await app.updater.stop()
                except Exception:
                    pass

        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_bootstrap())
        except Exception as exc:
            print(f"[telegram] bridge crashed: {exc}", flush=True)
        finally:
            self._ready.set()  # unblock anyone waiting even on error
            try:
                loop.close()
            except Exception:
                pass

    def _safe_handle(self, text: str, session_key: str | None = None) -> str:
        try:
            if self._llm_lock is not None:
                with self._llm_lock:
                    return self._call_handler(text, session_key) or ""
            return self._call_handler(text, session_key) or ""
        except Exception as exc:
            return f"(agent error: {type(exc).__name__}: {exc})"

    def _call_handler(self, text: str, session_key: str | None) -> str:
        """Handler signature is permissive: try the modern (text, session_key)
        form first, fall back to (text) for callers that haven't upgraded."""
        try:
            return self._handler(text, session_key=session_key) or ""
        except TypeError:
            return self._handler(text) or ""
