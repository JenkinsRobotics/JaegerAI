"""Persona tools — let the agent read + tune its OWN character's traits.

Peer of identity_tools (set_name / update_soul), but for the active
character's HEXACO / SPECIAL / Expression / Domains sliders. With trait-driven
prompts live, a change here shapes behavior from the next turn. Edits the
SELECTED character's sheet (in the library), not the instance.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.context import _require_layout, get_layout
from jaeger_os.agent.schemas.tool_registry import register_tool_from_function

_LAYERS = ("hexaco", "special", "expression", "domains")


def _active() -> Any:
    from jaeger_os.personality.character import active_character
    try:
        return active_character(_require_layout().root)
    except Exception:  # noqa: BLE001
        return None


def read_traits() -> dict[str, Any]:
    """Read your OWN character's personality sliders (0..1) — the HEXACO,
    SPECIAL, Expression, and Domains layers."""
    c = _active()
    if c is None:
        return {"ok": False, "error": "no active character selected"}
    from jaeger_os.personality.character import layer_items
    p = c.personality
    return {"ok": True, "character": c.name,
            **{k: dict(layer_items(getattr(p, k))) for k in _LAYERS}}


def adjust_trait(layer: str, field: str, value: float) -> dict[str, Any]:
    """Set one of your OWN character's personality sliders to ``value`` (0..1).

    ``layer`` is one of hexaco / special / expression / domains; ``field`` is
    the slider in that layer (e.g. layer="expression", field="sarcasm"). The
    change persists to the character and is live from your next turn."""
    c = _active()
    if c is None:
        return {"ok": False, "error": "no active character selected"}
    layer = (layer or "").lower().strip()
    if layer not in _LAYERS:
        return {"ok": False, "error": f"unknown layer {layer!r}; one of {list(_LAYERS)}"}
    from jaeger_os.personality.character import layer_items, save_character_traits
    cur = dict(layer_items(getattr(c.personality, layer)))
    if field not in cur:
        return {"ok": False, "error": f"unknown {layer} trait {field!r}; options: {sorted(cur)}"}
    try:
        v = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return {"ok": False, "error": f"value must be a number 0..1, got {value!r}"}
    cur[field] = v
    save_character_traits(c.root, {layer: cur})
    return {"ok": True, "character": c.name, "layer": layer, "field": field, "value": v}


@register_tool_from_function(name="remember_person")
def _t_remember_person(name: str, note: str = "", like: str = "", access: str = "",
                       channel: str = "", handle: str = "") -> dict:
    """Build or update a PROFILE of a person you interact with (the owner, a
    guest) in your person index — which you grow over time the way you grow
    skills. Use it whenever you learn something durable about someone:
      • note     — a durable fact about them (appended)
      • like     — something they like (appended)
      • access   — admin | member | blocked (their trust level)
      • channel + handle — link a messaging account to them (e.g. "telegram"
        + their chat id), so you know which accounts are this person.
    Distinct from CHARACTERS (the personas YOU play). Returns the profile."""
    from dataclasses import asdict
    from jaeger_os.core import people
    layout = get_layout()
    if layout is None:
        return {"ok": False, "error": "no instance bound"}
    p = people.upsert_person(layout, name=name, note=note, like=like,
                             access=(access or None), channel=channel.strip().lower(),
                             handle=handle)
    return {"ok": True, "person": asdict(p)}


@register_tool_from_function(name="get_person", side_effect="read")
def _t_get_person(name: str) -> dict:
    """Look up a person's profile (by name / alias) from your person index —
    answer "who is X?" / "what does X like?" from FACT, not a guess. Returns
    the profile or {found: false}."""
    from dataclasses import asdict
    from jaeger_os.core import people
    layout = get_layout()
    p = people.find_by_name(layout, name) if layout is not None else None
    if p is None:
        return {"found": False, "name": name}
    return {"found": True, "person": asdict(p)}


@register_tool_from_function(name="list_people", side_effect="read")
def _t_list_people() -> dict:
    """List everyone in your person index — names + access level. Use to
    recall who you know."""
    from jaeger_os.core import people
    layout = get_layout()
    if layout is None:
        return {"people": []}
    return {"people": [{"id": p.id, "name": p.name, "access": p.access}
                       for p in people.list_people(layout)]}
