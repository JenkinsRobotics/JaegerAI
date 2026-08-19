"""Runtime persona state — per-instance, never the character definition.

A character sheet (``personality/characters/<id>/character.yaml``) is a
DEFINITION: it ships with the package, is shared by every instance that
plays that character, and is what the marketplace distributes. Runtime
adaptation is the opposite thing — it belongs to one robot, on one host,
and it changes while the agent is talking to someone.

Those two were the same file. ``adjust_trait`` (the agent nudging its own
sliders mid-conversation) called ``save_character_traits``, which edits
the bundled sheet in place and bumps its ``revision``. Three consequences,
all of them silent: two instances playing ``assistant`` shared one set of
sliders, a package upgrade fought whatever the agent had learned, and a
character exported to the marketplace carried one deployment's drift.

This module is the other half: overrides live at
``<instance>/persona_state.yaml`` and are applied over the definition at
load time. The sheet stays pristine and distributable; the drift stays
with the instance that earned it. Same storage shape as the person index
(:mod:`jaeger_ai.core.people`) — one small YAML under the instance root,
hand-editable, greppable, no schema migration.

The Studio's trait EDITOR still writes the definition through
``save_character_traits``: an operator editing a character on purpose is
authoring, not adapting. Only the runtime path routes here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# The four trait layers a character carries. Anything else in the file is
# ignored rather than rejected — a newer build writing a fifth layer must
# not break an older one reading the file.
TRAIT_LAYERS = ("hexaco", "special", "expression", "domains")

STATE_FILENAME = "persona_state.yaml"


def state_path(instance_root: Path | Any) -> Path:
    """``<instance>/persona_state.yaml``. Accepts an instance root path or
    an :class:`InstanceLayout`.

    The Path check comes first on purpose: ``Path`` itself has a ``root``
    attribute (``"/"`` for an absolute path), so a bare ``getattr(x,
    "root", x)`` resolves a perfectly good path to the filesystem root.
    """
    root = instance_root
    if not isinstance(root, (str, Path)):
        root = getattr(root, "root", root)
    return Path(root) / STATE_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(instance_root: Path | Any) -> dict[str, Any]:
    """The whole state document, or ``{}``. Never raises: a corrupt or
    unreadable state file means "no overrides", not a dead agent."""
    try:
        path = state_path(instance_root)
        if not path.is_file():
            return {}
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — runtime state must never break boot
        return {}
    return doc if isinstance(doc, dict) else {}


def load_overrides(instance_root: Path | Any, character_id: str) -> dict[str, dict[str, float]]:
    """This instance's trait overrides for ``character_id``.

    Shape: ``{layer: {field: value}}``, values clamped to 0..1. Unknown
    layers and non-numeric values are dropped — the file is
    hand-editable, so it is read defensively.
    """
    characters = _read(instance_root).get("characters")
    if not isinstance(characters, dict):
        return {}
    entry = characters.get(character_id)
    if not isinstance(entry, dict):
        return {}
    traits = entry.get("traits")
    if not isinstance(traits, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for layer in TRAIT_LAYERS:
        values = traits.get(layer)
        if not isinstance(values, dict):
            continue
        clean: dict[str, float] = {}
        for field_name, raw in values.items():
            try:
                clean[str(field_name)] = max(0.0, min(1.0, float(raw)))
            except (TypeError, ValueError):
                continue
        if clean:
            out[layer] = clean
    return out


def set_trait_override(
    instance_root: Path | Any,
    character_id: str,
    layer: str,
    field_name: str,
    value: float,
) -> float:
    """Record one slider override for this instance. Returns the stored
    (clamped) value. Raises ``ValueError`` on an unknown layer — the
    caller validates the field name against the live character."""
    if layer not in TRAIT_LAYERS:
        raise ValueError(f"unknown trait layer {layer!r}; one of {list(TRAIT_LAYERS)}")
    try:
        clamped = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"trait value must be a number 0..1, got {value!r}") from exc

    doc = _read(instance_root)
    characters = doc.setdefault("characters", {})
    if not isinstance(characters, dict):
        characters = {}
        doc["characters"] = characters
    entry = characters.setdefault(character_id, {})
    if not isinstance(entry, dict):
        entry = {}
        characters[character_id] = entry
    traits = entry.setdefault("traits", {})
    if not isinstance(traits, dict):
        traits = {}
        entry["traits"] = traits
    traits.setdefault(layer, {})[field_name] = round(clamped, 3)
    entry["updated_at"] = _now()
    _write(instance_root, doc)
    return clamped


def clear_overrides(instance_root: Path | Any, character_id: str | None = None) -> None:
    """Drop overrides for one character, or all of them when
    ``character_id`` is None — "go back to the sheet as shipped"."""
    doc = _read(instance_root)
    characters = doc.get("characters")
    if not isinstance(characters, dict):
        return
    if character_id is None:
        doc["characters"] = {}
    else:
        characters.pop(character_id, None)
    _write(instance_root, doc)


def _write(instance_root: Path | Any, doc: dict[str, Any]) -> Path:
    path = state_path(instance_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at"] = _now()
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def apply_overrides(character: Any, overrides: dict[str, dict[str, float]]) -> Any:
    """Overlay ``overrides`` onto a loaded character, in place.

    Only fields the layer already declares are set: an override for a
    slider this character does not have is stale state (the sheet
    changed under it), and inventing the attribute would put a value
    somewhere nothing reads it from.
    """
    if not overrides:
        return character
    personality = getattr(character, "personality", None)
    if personality is None:
        return character
    for layer, values in overrides.items():
        struct = getattr(personality, layer, None)
        if struct is None:
            continue
        for field_name, value in values.items():
            if hasattr(struct, field_name):
                try:
                    setattr(struct, field_name, value)
                except Exception:  # noqa: BLE001 — frozen/odd layer: skip it
                    continue
    return character


def signature(instance_root: Path | Any) -> str:
    """``mtime`` of the state file — feeds the prompt-refresh signature so
    a trait the agent adjusts mid-session takes effect on the next turn."""
    try:
        return str(state_path(instance_root).stat().st_mtime)
    except OSError:
        return "0"


__all__ = [
    "TRAIT_LAYERS", "STATE_FILENAME", "state_path", "load_overrides",
    "set_trait_override", "clear_overrides", "apply_overrides", "signature",
]
