"""Plugins — drop-in modules adding external integrations.

A plugin bridges the agent to a specific external service or capability:
Discord, Telegram, iMessage, MCP servers, future Kokoro TTS, Whisper STT,
RealSense perception, YOLO classification, etc.

Each plugin lives in its own subdirectory with:
  • plugin.yaml      — manifest (deps, env vars, registered bridges, tools)
  • <module>.py      — the implementation
  • tests/smoke_test.py — importability check the loader runs before activation

This file holds the **shared bridge registry**. Bridges that successfully
start (i.e. opened a connection with valid credentials) call
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
    """Bridges call this from their `start()` once they're connected."""
    with _BRIDGES_LOCK:
        _BRIDGES[name] = bridge


def deregister_bridge(name: str) -> None:
    with _BRIDGES_LOCK:
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
            from jaeger_ai.core import credentials as creds
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


# channel → spec for the in-process bridges we can start on demand. ``allow_kw``
# is the bridge constructor's allowlist kwarg (telegram chats vs discord users).
_BRIDGE_SPECS = {
    "telegram": {"mod": ".telegram", "cls": "TelegramBridge", "token": "TELEGRAM_BOT_TOKEN",
                 "allow": "TELEGRAM_ALLOWED_CHAT_IDS", "allow_kw": "allowed_chats", "ints": True,
                 "admin": "TELEGRAM_ADMIN_IDS"},
    "discord":  {"mod": ".discord", "cls": "DiscordBridge", "token": "DISCORD_BOT_TOKEN",
                 "allow": "DISCORD_ALLOWED_USER_IDS", "allow_kw": "allowed_users", "ints": True,
                 "admin": "DISCORD_ADMIN_IDS"},
    # iMessage has NO bot token — it drives the local Messages app (macOS +
    # Full Disk Access). Its allowlist is string handles (phone / Apple ID).
    "imessage": {"mod": ".imessage", "cls": "IMessageBridge", "token": None,
                 "allow": "IMESSAGE_ALLOWED_HANDLES", "allow_kw": "allowed_handles", "ints": False,
                 "admin": "IMESSAGE_ADMIN_IDS"},
}


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
    import importlib

    channel = (name or "").strip().lower()
    if get_bridge(channel) is not None:
        return {"started": True, "channel": channel, "already_running": True}
    spec = _BRIDGE_SPECS.get(channel)
    if spec is None:
        return {"started": False, "channel": channel,
                "error": f"no in-process bridge for {channel!r}; known: {sorted(_BRIDGE_SPECS)}"}
    token = plugin_credential(layout, spec["token"]) if spec["token"] else ""
    if spec["token"] and not token:
        return {"started": False, "channel": channel,
                "error": f"no {spec['token']} in the instance credential store or env — "
                         f"ask the user for the value and set_credential it first, then "
                         f"retry (do not invent a token)"}
    raw_allow = plugin_credential(layout, spec["allow"]) if spec["allow"] else ""
    allowed = _parse_chat_ids(raw_allow) if spec["ints"] else _parse_handles(raw_allow)
    from ._messaging import parse_admin_ids
    admin_ids = parse_admin_ids(plugin_credential(layout, spec["admin"]))
    try:
        # The person index is the richer source of truth: anyone with
        # access=admin whose handles include this channel is the owner here.
        from jaeger_ai.core import people
        admin_ids |= people.admins_for_channel(layout, channel)
    except Exception:  # noqa: BLE001 — person index is optional
        pass
    try:
        mod = importlib.import_module(spec["mod"], __package__)
        kwargs = {"llm_lock": llm_lock, "bus": bus, spec["allow_kw"]: allowed,
                  "admin_ids": admin_ids}
        if spec["token"]:
            kwargs["token"] = token
        bridge = getattr(mod, spec["cls"])(handler, **kwargs)
        bridge.start()
    except Exception as exc:  # noqa: BLE001 — surface; a bad bridge never crashes the agent
        return {"started": False, "channel": channel, "error": f"{type(exc).__name__}: {exc}"}
    return {"started": True, "channel": channel}


__all__ = [
    "register_bridge", "deregister_bridge", "get_bridge", "list_bridges",
    "plugin_credential", "start_bridge",
]
