#!/usr/bin/env python3
"""Multi-channel messaging gateway for Jaeger.

Loads the Jaeger agent ONCE, then starts every messaging plugin that has
the env vars to authenticate. All channels share the same Gemma instance,
the same memory store, and the same skill / cron state.

  Discord plugin:   needs DISCORD_BOT_TOKEN, optional DISCORD_ALLOWED_USER_IDS
  Telegram plugin:  needs TELEGRAM_BOT_TOKEN, optional TELEGRAM_ALLOWED_CHAT_IDS
  iMessage plugin:  needs IMESSAGE_ALLOWED_HANDLES (macOS, Full Disk Access)

This file is not itself a plugin — it's the daemon entry point that
orchestrates the per-channel plugins (`plugins/discord/`, `plugins/telegram/`,
`plugins/imessage/`). Run:

    python -m jaeger_os.plugins.messaging_gateway
    python -m jaeger_os.plugins.messaging_gateway --no-imessage
    python -m jaeger_os.plugins.messaging_gateway --no-discord

Standalone process — loads its own LLM, runs the bridges. (The
``--attach`` flag that routed turns through a running daemon's
chat.send was removed 2026-06-14 with the daemon-arch decision —
each plugin now owns its own model, matching fused-mode philosophy.)

See docs/VOCABULARY.md for why plugins/ contains plugins (drop-in external
integrations) but the gateway daemon is a top-level orchestrator, not its
own plugin.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from typing import Any

from ..main import (
    LlamaCppPythonClient,
    init_extensions,
    prewarm,
    run_for_voice,
    shutdown_extensions,
)
from ..agent import tools as agent_tools
from jaeger_os.agent.background.cron_runner import CronRunner
from jaeger_os.core.instance.instance import InstanceLayout, default_instance_name, resolve_instance_dir
from jaeger_os.core.instance.schemas import Config, load_yaml
from jaeger_os.agent.prompts.prompts import build_system_prompt


def _make_handler(client: Any) -> "callable":
    """Wrap run_for_voice into a sync `text -> reply` callback.

    Each plugin passes its own `session_key` so the per-channel rolling
    history stays isolated (Telegram chat A doesn't see Discord chat B,
    etc.).
    """
    def handler(text: str, session_key: str | None = None) -> str:
        result = run_for_voice(client, text, session_key=session_key)
        return (result.get("text") or "").strip()
    return handler


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--instance", type=str, default=None,
                   help="Instance name (default: JAEGER_INSTANCE_NAME or 'default').")
    p.add_argument("--no-discord", action="store_true")
    p.add_argument("--no-telegram", action="store_true")
    p.add_argument("--no-imessage", action="store_true")
    p.add_argument("--no-cron", action="store_true")
    # NOTE — the --attach flag (which routed turns through a running
    # daemon's chat.send to skip an in-process LLM load) was removed
    # 2026-06-14 with the daemon-arch decision (J5C). The gateway
    # now always loads its own model and runs standalone, matching
    # fused-mode philosophy.
    args = p.parse_args()

    # Production posture: remote channels never destroy files or memory
    # without explicit user confirmation through the agent's ask_user tool.
    os.environ.setdefault("DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "1")

    # Resolve the instance and wire the layout into jaeger's tool surface.
    instance_name = args.instance or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(instance_name))
    if not layout.exists():
        print(f"[gateway] instance {instance_name!r} not initialized; "
              f"run `./run.sh setup {instance_name}` first.", file=sys.stderr)
        return 2

    config: Config = load_yaml(layout.config_path, Config)
    agent_tools.bind(layout)

    # Populate jaeger's pipeline (mirrors what main.main() does at startup).
    from ..main import _pipeline
    _pipeline["layout"] = layout
    _pipeline["config"] = config
    _pipeline["system_prompt"] = build_system_prompt(layout)
    _pipeline["show_latency"] = config.display.show_latency
    _pipeline["show_tool_activity"] = config.display.show_tool_activity

    # ── LLM bring-up — local model, always ──────────────────────────
    print(f"[gateway] loading Gemma in-process ({layout.root.name})...",
          flush=True)
    started = time.perf_counter()
    client = LlamaCppPythonClient(config.model, warmup=True)
    print(f"[gateway] loaded in {time.perf_counter() - started:.1f}s",
          flush=True)

    class _Args:
        with_memory = True
        with_mcp = False
        think = False
    init_extensions(_Args(), client)
    prewarm(client)
    handler = _make_handler(client)

    # Single lock guards all LLM access — Discord, Telegram, iMessage,
    # and cron all serialize through it so two channels can't decode
    # against the same KV cache simultaneously.
    llm_lock = threading.Lock()
    _pipeline["llm_lock"] = llm_lock

    adapters: list[Any] = []
    if not args.no_discord and os.environ.get("DISCORD_BOT_TOKEN"):
        try:
            from .discord import DiscordBridge
            d = DiscordBridge(handler, llm_lock=llm_lock)
            d.start()
            adapters.append(d)
            print("[gateway] Discord plugin started", flush=True)
        except Exception as exc:
            print(f"[gateway] Discord plugin skipped: {exc}", flush=True)
    elif not args.no_discord:
        print("[gateway] Discord plugin skipped: DISCORD_BOT_TOKEN unset", flush=True)

    if not args.no_telegram and os.environ.get("TELEGRAM_BOT_TOKEN"):
        try:
            from .telegram import TelegramBridge
            t = TelegramBridge(handler, llm_lock=llm_lock)
            t.start()
            adapters.append(t)
            print("[gateway] Telegram plugin started", flush=True)
        except Exception as exc:
            print(f"[gateway] Telegram plugin skipped: {exc}", flush=True)
    elif not args.no_telegram:
        print("[gateway] Telegram plugin skipped: TELEGRAM_BOT_TOKEN unset", flush=True)

    if not args.no_imessage and sys.platform == "darwin":
        try:
            from .imessage import IMessageBridge
            im = IMessageBridge(handler, llm_lock=llm_lock)
            im.start()
            adapters.append(im)
        except Exception as exc:
            print(f"[gateway] iMessage plugin skipped: {exc}", flush=True)

    cron_runner: CronRunner | None = None
    if not args.no_cron:
        def _cron_callback(prompt: str, session_key: str | None = None) -> None:
            handler(prompt, session_key=session_key)
        cron_runner = CronRunner(_cron_callback, llm_lock=llm_lock)
        cron_runner.start()
        print("[gateway] cron runner started", flush=True)

    if not adapters and cron_runner is None:
        print("[gateway] no adapters started — nothing to do; exiting", flush=True)
        return 1

    print("[gateway] ready. Ctrl-C to quit.", flush=True)
    stop = threading.Event()

    def _shutdown(*_: Any) -> None:
        print("\n[gateway] shutdown signal received", flush=True)
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    try:
        while not stop.is_set():
            stop.wait(1.0)
    finally:
        if cron_runner is not None:
            cron_runner.shutdown(wait=False)
        for ad in adapters:
            try:
                ad.stop()
            except Exception as exc:
                print(f"[gateway] adapter stop failed: {exc}", flush=True)
        shutdown_extensions(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
