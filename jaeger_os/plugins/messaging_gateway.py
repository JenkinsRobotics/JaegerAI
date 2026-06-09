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

0.2.6: ``--attach`` mode lets the gateway run alongside a daemon
without loading a second LLM. The bridges still own the channel I/O
(socket connections to Discord / Telegram / iMessage); the agent
turn itself is delegated to the daemon over the local socket.
Together with the voice loop's --attach flag this is what makes
"daemon + voice + messaging" fit on a 32 GB Mac — a single model in
RAM, regardless of how many client surfaces are active.

    python -m jaeger_os.plugins.messaging_gateway --instance jros-dev --attach

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
from jaeger_os.core.background.cron_runner import CronRunner
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


def _make_attached_handler(daemon_client: Any) -> "callable":
    """Same shape as :func:`_make_handler` but routes through the
    daemon's ``chat.send`` instead of an in-process LLM.

    Per-channel session_key still flows through verbatim — the
    daemon's chat_ops stores rolling history per session_key, so
    Discord chat A and Telegram chat B stay isolated exactly the
    same way as in standalone mode.

    Blocking semantics match the standalone handler: the call returns
    when the agent turn completes (or the call_timeout fires).
    Bridges already absorb that latency on their own threads; no
    behavioural change from their POV.
    """
    def handler(text: str, session_key: str | None = None) -> str:
        resp = daemon_client.call(
            "chat.send", text=text, session_key=session_key,
        )
        data = getattr(resp, "data", None) or {}
        return (data.get("text") or "").strip()
    return handler


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--instance", type=str, default=None,
                   help="Instance name (default: JAEGER_INSTANCE_NAME or 'default').")
    p.add_argument("--no-discord", action="store_true")
    p.add_argument("--no-telegram", action="store_true")
    p.add_argument("--no-imessage", action="store_true")
    p.add_argument("--no-cron", action="store_true")
    # 0.2.6: attach to a running daemon instead of loading our own LLM.
    # When set, the gateway opens a socket to <instance>/run/jaeger.sock
    # and routes every channel's turn through chat.send. Bridges keep
    # owning Discord / Telegram / iMessage I/O; only the agent itself
    # is delegated. Exits with a clear error if the daemon isn't up.
    p.add_argument(
        "--attach", action="store_true",
        help="Skip in-process LLM load; route turns through a running "
             "daemon's chat.send verb. Required for multi-client setups "
             "where the daemon + voice loop + messaging gateway should "
             "share one model in RAM."
    )
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

    # ── LLM bring-up: either local or via daemon attach ──────────────
    # Local (default): same as 0.2.0+. Loads Gemma in-process, runs
    # init_extensions + prewarm, builds an in-process handler.
    # --attach: skips the local model entirely. Each turn calls
    # ``Client.call('chat.send', ...)`` against the daemon's socket.
    daemon_client = None
    client = None  # the local LLM client; populated in non-attach mode
    if args.attach:
        from jaeger_os.daemon.client import Client, DaemonNotRunning
        sock_path = layout.root / "run" / "jaeger.sock"
        if not sock_path.exists():
            print(f"[gateway] --attach: daemon socket missing at {sock_path}.",
                  file=sys.stderr)
            print("          Start the daemon first: ./run.sh start"
                  f" --instance {instance_name}", file=sys.stderr)
            return 2
        try:
            daemon_client = Client(socket_path=sock_path, call_timeout=600.0)
            daemon_client.__enter__()
        except DaemonNotRunning as exc:
            print(f"[gateway] --attach: cannot connect to daemon — {exc}.",
                  file=sys.stderr)
            print("          Start the daemon first: ./run.sh start"
                  f" --instance {instance_name}", file=sys.stderr)
            return 2
        print(f"[gateway] attached to daemon at {sock_path}", flush=True)
        handler = _make_attached_handler(daemon_client)
    else:
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
    #
    # In --attach mode the daemon's chat_ops does its own serialization
    # behind chat.send, so this lock is effectively a no-op. Kept so the
    # bridge constructors keep their signatures unchanged.
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

    # 0.2.6: skip the local cron runner in --attach mode. The daemon
    # already runs schedules; spinning up a second runner here would
    # fire each cron prompt twice.
    cron_runner: CronRunner | None = None
    if not args.no_cron and not args.attach:
        def _cron_callback(prompt: str, session_key: str | None = None) -> None:
            handler(prompt, session_key=session_key)
        cron_runner = CronRunner(_cron_callback, llm_lock=llm_lock)
        cron_runner.start()
        print("[gateway] cron runner started", flush=True)
    elif args.attach:
        print("[gateway] cron runner skipped (daemon owns the schedules)",
              flush=True)

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
        # 0.2.6: release the daemon socket in --attach mode. Skip
        # shutdown_extensions there too — the daemon owns the
        # extensions, this process never initialised them.
        if daemon_client is not None:
            try:
                daemon_client.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        else:
            shutdown_extensions(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
