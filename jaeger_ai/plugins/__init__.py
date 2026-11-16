"""Plugins — drop-in modules adding external integrations.

A plugin bridges the agent to a specific external service or capability:
Discord, Telegram, iMessage, MCP servers, future Kokoro TTS, Whisper STT,
RealSense perception, YOLO classification, etc.

Each plugin lives in its own subdirectory with:
  • plugin.yaml      — manifest (deps, env vars, registered bridges, tools)
  • <module>.py      — the implementation
  • tests/smoke_test.py — importability check the loader runs before activation

This file holds the **shared bridge registry**. Bridges registered by their transport lifecycle call
`register_bridge("<channel>", self)`. The agent's `send_message(channel,
recipient, text)` tool reads the registry to route outbound messages.

See docs/VOCABULARY.md for the full contract on what is and isn't a plugin.
"""

from __future__ import annotations

import threading
from typing import Any


# {channel_name → bridge_instance}. Populated by each bridge when it
# successfully starts; read by core's send_message tool. A lock guards
# the dict so the gateway can register/deregister without races against
# concurrent tool calls.
_BRIDGES: dict[str, Any] = {}
_BRIDGES_LOCK = threading.Lock()


def register_bridge(name: str, bridge: Any) -> None:
    """Register an owned transport handle; registration is not health proof."""
    with _BRIDGES_LOCK:
        _BRIDGES[name] = bridge


def deregister_bridge(name: str, *, expected: Any = None) -> None:
    with _BRIDGES_LOCK:
        if expected is None or _BRIDGES.get(name) is expected:
            _BRIDGES.pop(name, None)


def get_bridge(name: str) -> Any:
    with _BRIDGES_LOCK:
        return _BRIDGES.get(name)


def list_bridges() -> list[str]:
    with _BRIDGES_LOCK:
        return sorted(_BRIDGES.keys())


# ── instance-folder credentials (plugins reference the instance, not env) ──

def plugin_credential(layout: Any, name: str) -> str:
    """Resolve a plugin credential by NAME, **instance-folder first**.

    A plugin belongs to the running agent instance, so its secrets live in the
    per-instance credential store (``<instance>/credentials/`` — what the
    agent's ``set_credential`` writes), NOT in process env. We read the store
    first and fall back to an env var of the same name only for legacy /
    headless launches (the standalone gateway). Returns ``""`` if neither has
    it."""
    if layout is not None:
        try:
            from jaeger_agent.core import credentials as creds
            return creds.get_credential(layout, name)
        except Exception:  # noqa: BLE001 — absent/garbled in the store → try env
            pass
    import os
    return (os.environ.get(name) or "").strip()


def _parse_chat_ids(raw: str) -> set[int]:
    out: set[int] = set()
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if tok:
            try:
                out.add(int(tok))
            except ValueError:
                pass
    return out


# Phone channels live in ONE place: the standalone channels relay
# (``jaeger_ai.features.channels.relay``, launchd ``jaeger-channels``), which
# runs Telegram + iMessage for the owner only. The old in-process bridges
# (plugins/telegram|imessage|discord) were archived to
# ~/Desktop/Jaeger-removed-features-2026-11-16/in-process-channel-bridges/.
_RELAY_CHANNELS = {"telegram", "imessage"}
_BRIDGE_SPECS: dict[str, dict] = {}


def _parse_handles(raw: str) -> set[str]:
    return {h.strip() for h in (raw or "").split(",") if h.strip()}


def start_bridge(name: str, *, layout: Any, handler: Any, llm_lock: Any = None,
                 bus: Any = None) -> dict:
    """Start a plugin's bridge as a background thread IN THIS process, wired to
    the live agent: its ``handler`` runs turns (so the same model / memory /
    persona answers every channel) and its credential comes from the instance
    store. The bridge calls ``register_bridge`` on connect, so ``send_message``
    then finds it. Returns a status dict; never raises.

    ``llm_lock`` is passed through but in-process callers pass ``None`` — the
    turn already serializes on ``_pipeline['llm_lock']`` inside ``_run_turn``,
    and that lock is non-reentrant, so a second acquire here would deadlock."""
    channel = (name or "").strip().lower()
    if get_bridge(channel) is not None:
        return {"started": True, "channel": channel, "already_running": True}
    if channel in _RELAY_CHANNELS:
        return {"started": False, "channel": channel, "relay": True,
                "error": (f"{channel} runs in the channels relay service, not in this process. "
                          "Setup: put JAEGER_TELEGRAM_BOT_TOKEN in ~/.jaeger/secrets.env (Telegram) "
                          "or add your own handle in Settings > Channels (iMessage); the relay "
                          "(launchd com.jenkinsrobotics.jaeger-channels) delivers send_message "
                          "to the owner's chat.")}
    return {"started": False, "channel": channel,
            "error": (f"no bridge for {channel!r}. Discord's old in-process bridge is archived "
                      "on the Desktop (candidate to port back into the relay).")}


__all__ = [
    "register_bridge", "deregister_bridge", "get_bridge", "list_bridges",
    "plugin_credential", "start_bridge",
]
