"""Persona tools — let the agent read + tune its OWN character's traits.

Peer of identity_tools (set_name / update_soul), but for the active
character's HEXACO / SPECIAL / Expression / Domains sliders. With trait-driven
prompts live, a change here shapes behavior from the next turn. Edits the
SELECTED character's sheet (in the library), not the instance.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.context import _require_layout

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
