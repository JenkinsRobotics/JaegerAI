"""``jaeger personality`` — view + adjust the active instance's persona.

Operator-facing.  The GUI's Character Sheet tab reads the same file
this command writes to (``<instance>/personality.json``).
"""

from __future__ import annotations

from typing import Any

import msgspec

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "personality",
        help="view + adjust persona stats (HEXACO, expression, etc.)",
        description=(
            "Inspect the active instance's persona — same data the "
            "brain reads every turn.  ``jaeger personality set "
            "expression.directness 0.85`` adjusts a field."
        ),
    )
    parser.set_defaults(_handler=run_view)
    sub = parser.add_subparsers(dest="personality_subcommand")
    sub.required = False

    view = sub.add_parser("view", help="render the persona (default)")
    view.set_defaults(_handler=run_view)

    setp = sub.add_parser(
        "set", help="adjust a field — ``jaeger personality set <field> <value>``",
    )
    setp.add_argument(
        "field",
        help="dotted path: expression.directness, hexaco.openness, "
             "special.charisma, domains.science, name",
    )
    setp.add_argument("value", help="new value (float for sliders; "
                                     "string for name)")
    setp.set_defaults(_handler=run_set)


def _load() -> tuple[Any | None, Any | None]:
    """Return (layout, personality) or (None, None) on any failure."""
    layout = c.get_active_instance_layout()
    if layout is None:
        return None, None
    pj = layout.root / "personality.json"
    if not pj.exists():
        # Synthesize an empty personality so ``set`` can populate
        # from scratch; callers can re-check existence via the
        # path.
        from jaeger_ai.personality import Personality
        return layout, Personality(name=layout.root.name)
    try:
        from jaeger_ai.personality import load_personality
        return layout, load_personality(pj)
    except Exception:  # noqa: BLE001
        return layout, None


# ── view ──────────────────────────────────────────────────────────

def run_view(args: Any) -> int:
    layout, p = _load()
    if layout is None:
        print(c.red("no active instance"))
        return 1
    if p is None:
        print(c.red("personality.json exists but couldn't be parsed"))
        return 1
    pj_exists = (layout.root / "personality.json").exists()
    print()
    print(f"  {c.bold('Persona')}: {c.cyan(p.name or '(unnamed)')}"
          + (c.dim("  (no personality.json — defaults shown)")
             if not pj_exists else ""))
    if p.description:
        print(f"  {c.dim(p.description)}")
    print()
    print(c.bold("  Expression"))
    _slider("    sarcasm",    p.expression.sarcasm)
    _slider("    warmth",     p.expression.warmth)
    _slider("    verbosity",  p.expression.verbosity)
    _slider("    formality",  p.expression.formality)
    _slider("    directness", p.expression.directness)
    _slider("    humor",      p.expression.humor)
    _slider("    empathy",    p.expression.empathy)
    _slider("    aggression", p.expression.aggression)
    print()
    print(c.bold("  HEXACO"))
    _slider("    openness",          p.hexaco.openness)
    _slider("    conscientiousness", p.hexaco.conscientiousness)
    _slider("    extraversion",      p.hexaco.extraversion)
    _slider("    agreeableness",     p.hexaco.agreeableness)
    _slider("    neuroticism",       p.hexaco.neuroticism)
    _slider("    honesty_humility",  p.hexaco.honesty_humility)
    print()
    print(c.bold("  SPECIAL"))
    _slider("    perception",   p.special.perception)
    _slider("    charisma",     p.special.charisma)
    _slider("    intelligence", p.special.intelligence)
    _slider("    endurance",    p.special.endurance)
    _slider("    agility",      p.special.agility)
    _slider("    strength",     p.special.strength)
    _slider("    luck",         p.special.luck)
    print()
    print(c.bold("  Domains"))
    _slider("    science",    p.domains.science)
    _slider("    philosophy", p.domains.philosophy)
    _slider("    technology", p.domains.technology)
    _slider("    art",        p.domains.art)
    _slider("    politics",   p.domains.politics)
    _slider("    psychology", p.domains.psychology)
    _slider("    nature",     p.domains.nature)
    _slider("    combat",     p.domains.combat)
    if p.speech_patterns:
        print()
        print(c.bold("  Speech patterns"))
        for sp in p.speech_patterns:
            print(f"    - {sp}")
    print()
    return 0


def _slider(label: str, value: float) -> None:
    print(f"  {label:<28} {c.bar(value)}  {value:.2f}")


# ── set ───────────────────────────────────────────────────────────

def run_set(args: Any) -> int:
    layout, p = _load()
    if layout is None:
        print(c.red("no active instance"))
        return 1
    if p is None:
        print(c.red("personality.json exists but couldn't be parsed"))
        return 1
    field_path = args.field.strip()
    raw_value = args.value
    try:
        updated = _apply_field(p, field_path, raw_value)
    except (KeyError, AttributeError) as exc:
        print(c.red(f"unknown field: {exc}"))
        return 1
    except ValueError as exc:
        print(c.red(f"bad value: {exc}"))
        return 1
    pj = layout.root / "personality.json"
    from jaeger_ai.personality import save_personality
    save_personality(updated, pj)
    print(c.green(f"updated {field_path} = {raw_value}"))
    print(c.dim(f"saved: {pj}"))
    return 0


def _apply_field(p: Any, dotted: str, raw_value: str) -> Any:
    """Return a new Personality with ``dotted`` field set."""
    parts = dotted.split(".")
    if len(parts) == 1:
        # Top-level string field (name, description,
        # custom_instructions).  Validate via msgspec.
        if parts[0] not in ("name", "description", "custom_instructions"):
            raise KeyError(parts[0])
        return msgspec.structs.replace(p, **{parts[0]: raw_value})
    if len(parts) != 2:
        raise KeyError(dotted)
    group, leaf = parts
    if group not in ("expression", "hexaco", "special", "domains"):
        raise KeyError(group)
    sub = getattr(p, group)
    # All sub-group fields are floats in [0, 1].
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"expected float 0..1; got {raw_value!r}") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"value must be in [0, 1]; got {value}")
    if not hasattr(sub, leaf):
        raise AttributeError(f"{group}.{leaf}")
    new_sub = msgspec.structs.replace(sub, **{leaf: value})
    return msgspec.structs.replace(p, **{group: new_sub})
