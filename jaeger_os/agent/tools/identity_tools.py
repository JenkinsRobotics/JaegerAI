"""Self-update tools — let the agent edit its OWN identity.

Who the agent is lives in two files at the instance root:
  • identity.yaml — structured facts (name, role). Code keys off these:
    the system-prompt header, the voice wake word, the TTS voice.
  • soul.md       — free-form prose: character, values, voice, the
    agent's own narrative of who it is.

Both sit OUTSIDE the skills/ sandbox, so the ordinary write_file tool
cannot reach them — which is exactly why a small model asked to "update
your name" once fell back to misusing remember(). These two tools close
that gap. A change rebuilds the system prompt and drops the cached
agent, so it is live from the agent's next turn.
"""

from __future__ import annotations

from typing import Any

from ._common import _require_layout


_ILLEGAL_NAME_CHARS = set('/\\:*?"<>|')
_SOUL_HEADER = (
    "<!-- soul.md — who this instance is: character, values, voice.\n"
    "     The agent maintains this via update_soul; the user may edit it\n"
    "     freely too. Loaded into the system prompt at startup. -->\n\n"
)
_SOUL_MAX_CHARS = 8000


def set_name(name: str) -> dict[str, Any]:
    """Change your OWN name — write it into identity.yaml.

    Use this when the user renames you ("your name is …", "I'll call you
    …", "rename yourself …"). This is your real, structured identity —
    do NOT store your own name with remember(); remember() is for facts
    about the USER. The change is live from your next turn."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "name is empty"}
    if len(name) > 64:
        return {"ok": False, "error": "name too long (64 character max)"}
    if _ILLEGAL_NAME_CHARS & set(name):
        return {"ok": False, "error": "name contains illegal characters"}

    try:
        layout = _require_layout()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"no active instance: {exc}"}

    from jaeger_os.core.instance.schemas import Identity, dump_yaml, load_yaml
    try:
        ident = load_yaml(layout.identity_path, Identity)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"couldn't read identity.yaml: {exc}"}
    old = ident.name
    ident.name = name
    try:
        dump_yaml(layout.identity_path, ident)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"couldn't write identity.yaml: {exc}"}

    _apply_identity_change()
    return {
        "ok": True, "old_name": old, "name": name,
        "note": "Name updated in identity.yaml — effective from your next turn.",
    }


def update_soul(content: str) -> dict[str, Any]:
    """Rewrite your soul.md — the free-form document of WHO YOU ARE:
    your character, values, voice and self-narrative.

    Pass the COMPLETE new soul text. Your current soul is already in
    your system prompt — read it, revise it, and pass the full revised
    version (this replaces the whole file). Personality and durable
    facts about YOURSELF belong here, not in remember(). Live from your
    next turn."""
    content = (content or "").strip()
    if not content:
        return {"ok": False, "error": "soul content is empty"}
    if len(content) > _SOUL_MAX_CHARS:
        return {"ok": False,
                "error": f"soul too long ({_SOUL_MAX_CHARS} character max)"}

    try:
        layout = _require_layout()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"no active instance: {exc}"}

    soul_path = layout.root / "soul.md"
    try:
        soul_path.write_text(_SOUL_HEADER + content + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"couldn't write soul.md: {exc}"}

    _apply_identity_change()
    return {
        "ok": True, "chars": len(content),
        "note": "soul.md updated — effective from your next turn.",
    }


def _apply_identity_change() -> None:
    """Rebuild the system prompt + drop the cached agent so a name/soul
    change is live on the next turn. Best-effort — a failure here just
    defers the change to the next reboot."""
    try:
        from ...main import refresh_identity
        refresh_identity()
    except Exception:  # noqa: BLE001
        pass
