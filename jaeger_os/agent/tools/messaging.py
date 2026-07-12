"""Messaging tools — proactively message a user, or certify an admin, on an
external channel (discord / telegram / imessage).

Migrated out of ``main.py::_register_builtins`` (tool-standardization pass).
These used to be closures in main.py; they don't actually need the LLM
``client`` — ``send_message`` talks to the messaging bridges, and
``certify_admin`` needs the layout + current session. Both now reach runtime
state through ``core.context`` accessors, so they live in ``tools/`` like
every other tool. Registered on import (see ``_register_builtins``).
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.context import get_current_session, get_layout
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier


@register_tool_from_function
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="messaging",
               operation="send_message",
               summary="send a message on an external channel")
def send_message(channel: str, recipient: str, text: str) -> dict:
    """Send a proactive message to a user on a messaging channel.

    Available `channel` values depend on which bridges are live in
    this process — typically "discord", "telegram", "imessage".
    `recipient` is the channel-specific ID (numeric Discord user ID,
    Telegram chat ID, or iMessage phone/Apple-ID handle).

    Use this together with `schedule_prompt` to send unattended
    notifications: schedule a prompt that says "send the weather to
    Discord user 12345" and the cron runner will fire it on time.
    """
    text_clean = (text or "").strip()
    channel_clean = (channel or "").strip().lower()
    recipient_clean = (recipient or "").strip()
    if not channel_clean or not recipient_clean or not text_clean:
        return {"sent": False, "error": "channel, recipient, and text are all required"}
    try:
        from jaeger_os.plugins import get_bridge, list_bridges
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "error": f"messaging plugin not importable: {exc}"}
    bridge = get_bridge(channel_clean)
    if bridge is None:
        return {
            "sent": False,
            "error": (f"no {channel_clean!r} bridge is running in this process. "
                      f"Start it with activate_plugin({channel_clean!r}) — it reads "
                      f"the credential you saved with set_credential. Live bridges: "
                      f"{list_bridges()}"),
        }
    try:
        return bridge.send(recipient_clean, text_clean)
    except Exception as exc:  # noqa: BLE001
        return {"sent": False, "error": f"bridge.send failed: {type(exc).__name__}: {exc}"}


@register_tool_from_function
def certify_admin(channel: str, identifier: str) -> dict:
    """Certify a remote messaging account as the OWNER (admin) — e.g.
    certify_admin("telegram", "8777030623") or ("discord", "<user id>").

    ADMIN-ONLY: this only works when YOU run it from an admin context (the
    desktop / TUI, or an already-certified account). A stranger on the bot
    CANNOT self-certify — it's denied for non-admin sessions. After this,
    that account gets slash commands + approvals + higher-tier actions;
    everyone else stays conversation-only. Stores the id in the channel's
    <CHANNEL>_ADMIN_IDS credential. Returns {ok, channel, admins}."""
    cur = get_current_session()
    from jaeger_os.core.safety.session_trust import is_admin_session, mark_session
    if not is_admin_session(cur):
        return {"ok": False, "error": "not authorized — only the owner (an admin "
                                      "session) can certify admins"}
    ch = (channel or "").strip().lower()
    if ch not in ("telegram", "discord", "imessage"):
        return {"ok": False, "error": f"unknown channel {ch!r} (telegram/discord/imessage)"}
    ident = (identifier or "").strip()
    if not ident:
        return {"ok": False, "error": "identifier required (the account id / handle)"}
    layout = get_layout()
    cred = f"{ch.upper()}_ADMIN_IDS"
    from jaeger_os.core import credentials as creds
    try:
        existing = creds.get_credential(layout, cred)
    except Exception:  # noqa: BLE001 — not set yet
        existing = ""
    ids = {x.strip() for x in existing.split(",") if x.strip()}
    ids.add(ident)
    creds.set_credential(layout, cred, ",".join(sorted(ids)))
    mark_session(f"{ch}:{ident}", True)   # instant effect for a live session
    # Also record the owner in the person index (one source of truth).
    try:
        from jaeger_os.core import people
        people.upsert_person(layout, name="Owner",
                             access="admin", channel=ch, handle=ident)
    except Exception:  # noqa: BLE001 — best-effort
        pass
    return {"ok": True, "channel": ch, "admins": sorted(ids)}
