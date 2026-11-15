"""``user_profile`` — Jaeger keeps the owner's profile (memory/USER.md) current."""

from __future__ import annotations

from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.core.workspace import _require_layout
from jaeger_agent.memory import user_profile as up


@register_tool_from_function(name="user_profile", side_effect="write")
def user_profile(action: str = "view", text: str = "", section: str = "Preferences",
                 old: str = "") -> dict[str, Any]:
    """Read or update the owner's profile — the short document of who they are
    and how they like things done, shown to you at the start of every chat.

    Use it when you learn something DURABLE about the owner: a preference
    ("prefers short answers"), a standing fact (job, timezone, family names they
    use), a working-style rule, or an active project. Not for one-off task
    details, and never for secrets, tokens or codes.

    action:
      • "view"    — current profile text.
      • "add"     — append ``text`` as one bullet under ``section``
                    (About | Preferences | Working style | Projects).
      • "replace" — replace the exact text ``old`` with ``text`` (correct or
                    update an entry); pass text="" to remove ``old``.
    Keep entries one line each; the whole profile is capped at 3000 chars.
    """
    layout = _require_layout()
    act = (action or "view").strip().lower()
    try:
        if act == "view":
            body = up.load(layout)
            return {"ok": True, "profile": body, "chars": len(body), "limit": up.MAX_CHARS}
        if act == "add":
            return up.add(layout, text, section, origin="jaeger")
        if act in ("replace", "remove"):
            return up.replace(layout, old, text if act == "replace" else "", origin="jaeger")
        return {"ok": False, "error": "action must be view, add or replace"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


__all__ = ["user_profile"]
