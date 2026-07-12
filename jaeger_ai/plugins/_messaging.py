"""Channel-agnostic messaging behaviour shared by every in-process bridge, so
the agent acts identically on Telegram / Discord / iMessage:

  • in-channel approvals — surface a mid-turn AgentRequest, capture the reply
  • slash commands (/mode …) — ADMIN-ONLY, handled in-channel (not sent to the LLM)

Each bridge keeps its own async/sync send + event loop; these pure helpers are
the agnostic guts. Trust (who's the owner) is per-session via
``core.safety.session_trust`` — the bridge resolves its admin set, marks each
session before the turn, and gates slash commands on it.
"""

from __future__ import annotations

from typing import Any


def parse_admin_ids(raw: str) -> set[str]:
    """The owner's certified account ids/handles for a channel (the
    ``<CHANNEL>_ADMIN_IDS`` credential), comma-separated."""
    return {x.strip() for x in (raw or "").split(",") if x.strip()}


def session_for(channel: str, recipient: str) -> str:
    return f"{channel}:{recipient}"


def recipient_for(channel: str, session: str) -> str | None:
    pre = f"{channel}:"
    return session[len(pre):] if session.startswith(pre) else None


# ── approvals ───────────────────────────────────────────────────────
def request_to_prompt(channel: str, msg: Any, awaiting: dict) -> tuple[str, str] | None:
    """A mid-turn AgentRequest arrived. If it's for one of THIS channel's chats,
    register the awaiting recipient and return (recipient, prompt_text) for the
    bridge to send. None if not ours. (Non-admins are auto-denied upstream, so a
    request only ever reaches here for an admin session.)"""
    recipient = recipient_for(channel, getattr(msg, "session", "") or "")
    rid = getattr(msg, "id", "")
    if recipient is None or not rid:
        return None
    awaiting[recipient] = rid
    prompt = getattr(msg, "prompt", "") or "Approve this action?"
    options = list(getattr(msg, "options", ()) or ["allow", "deny"])
    return recipient, f"🔐 {prompt}\nReply: {' / '.join(options)}"


def reply_as_approval(channel: str, recipient: str, text: str,
                      awaiting: dict, bus: Any) -> bool:
    """If we're awaiting this recipient's approval, publish the AgentResponse and
    return True (so the bridge does NOT run a turn)."""
    rid = awaiting.pop(recipient, None)
    if rid is None or bus is None:
        return False
    from jaeger_ai.core.messages import AgentResponse
    bus.publish(AgentResponse(id=rid, answer=text, session=session_for(channel, recipient)))
    return True


# ── slash commands (admin-only) ─────────────────────────────────────
def is_slash(text: str) -> bool:
    return (text or "").strip().startswith("/")


def mode_command(text: str) -> dict:
    """Parse ``/mode [name]``. Returns ``{}`` if not /mode; ``{"reply": str}``
    for a status/error to send; or ``{"ack": str, "switch": target}`` (the
    bridge sends ack, runs set_mode OFF its loop, then sends ``mode_result``)."""
    parts = text[1:].split() if is_slash(text) else []
    if not parts or parts[0].lower() != "mode":
        return {}
    from jaeger_ai.core.runtime import modes
    opts = ", ".join(modes.list_modes())
    if len(parts) < 2:
        return {"reply": f"mode: {modes.current_mode()}\noptions: {opts}\n/mode <name>"}
    target = parts[1].strip().lower()
    if target not in modes.list_modes():
        return {"reply": f"unknown mode '{target}'\noptions: {opts}"}
    return {"ack": f"switching to {target} mode… (model swap ~60-90s)", "switch": target}


def mode_result(res: Any, target: str) -> str:
    ok = isinstance(res, dict) and res.get("ok")
    return (f"◆ mode: {res.get('mode', target)}" if ok
            else f"✗ {res.get('error') if isinstance(res, dict) else 'switch failed'}")


def _autonomy_reply(res: Any, target: str, opts: str) -> str:
    if isinstance(res, dict) and res.get("ok"):
        return f"◆ autonomy: {res.get('mode', target)}"
    err = res.get("error") if isinstance(res, dict) else "switch failed"
    return f"✗ {err}\noptions: {opts}"


def autonomy_command(text: str) -> dict:
    """Parse the autonomy slash commands and APPLY them (switching is instant —
    no model swap, so no ack/run dance like ``/mode``). Handles the shortcuts
    ``/ask`` ``/scoped`` ``/auto`` and explicit ``/autonomy [name]``. Returns
    ``{"reply": str}`` for the bridge to send, or ``{}`` if not an autonomy
    command (the bridge then tries ``/mode``)."""
    if not is_slash(text):
        return {}
    parts = text[1:].split()
    if not parts:
        return {}
    from jaeger_ai.core.runtime import autonomy
    cmd = parts[0].lower()
    opts = ", ".join(autonomy.list_autonomy())
    if cmd in autonomy.list_autonomy():                       # /ask /scoped /auto
        return {"reply": _autonomy_reply(autonomy.set_autonomy(cmd), cmd, opts)}
    if cmd == "autonomy":
        if len(parts) < 2:                                    # bare → status
            return {"reply": f"autonomy: {autonomy.current_autonomy()}\n"
                             f"options: {opts}\n/autonomy <name>"}
        target = parts[1].strip().lower()
        return {"reply": _autonomy_reply(autonomy.set_autonomy(target), target, opts)}
    return {}


SLASH_DENIED = "⛔ commands are owner-only — you have conversation access."
SLASH_UNKNOWN = "unknown command — try /mode"
