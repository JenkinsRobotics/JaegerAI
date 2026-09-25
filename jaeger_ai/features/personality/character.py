"""Character — a library preset on top of :class:`Personality`.

``characters/`` owns the character library and its logic: :mod:`schema` holds
the trait model
(HEXACO/SPECIAL/Expression/Domains + custom_instructions) and :mod:`compose`
renders it into the system prompt. A *character* is just that ``Personality``
plus the library extras — identity (role/voice), backstory, and assets
(card/avatar) — stored as a folder ``characters/<id>/``.

The folder manifest follows the ecosystem ``character/v1`` package shape used
by Mochi and JaegerAnimation.  Jaeger AI owns the speaking/agentic half and
retains its trait/progression extensions; render-capable consumers can use the
same pack's typed assets and render declaration without a conversion step.

The live character view compiles these fields into behavioral language. Raw
trait ratings remain structured state for editing and evaluation; the model
receives the authored narrative, values, behavior, mannerisms, and strong trait
deviations rather than a numeric dump.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import msgspec
import yaml

from jaeger_ai.features.personality.schema import (
    HEXACO, SPECIAL, Domains, Expression, Personality,
)

CHARACTER_SCHEMA = "character/v1"


def _asset_reference(spec: Any) -> str:
    """Return a relative path from either generation of asset declaration.

    Older Jaeger AI sheets use ``assets: {card: card.png}``; the ecosystem
    format uses ``assets: {primary: {file: card.png, type: image, ...}}``.
    Reading both keeps operator-created packs working while every newly written
    pack is portable.
    """
    if isinstance(spec, str):
        return spec
    if isinstance(spec, dict):
        return str(spec.get("file") or spec.get("root") or "")
    return ""



def _u(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5


def _layer(cls: type, data: dict[str, Any]) -> Any:
    known = set(cls.__struct_fields__)
    return cls(**{k: _u(v) for k, v in (data or {}).items() if k in known})


@dataclass
class Character:
    """A character = a :class:`Personality` + identity + assets."""

    id: str
    personality: Personality
    version: str = "0.0.0"
    author: str = ""
    license: str = "Unspecified"
    role: str = ""
    voice_tone: str = ""
    voice_id: str = "af_heart"
    backstory: str = ""
    soul: str = ""
    quotes: tuple[str, ...] = ()
    mannerisms: tuple[str, ...] = ()
    ideals: tuple[str, ...] = ()
    behaviors: tuple[str, ...] = ()
    card: str = ""
    avatar_dir: str = "avatar"
    # ``character/v1`` assets are typed mappings (``file`` or ``root``).
    # String values remain accepted for pre-standard Jaeger AI packs.
    assets: dict[str, Any] = field(default_factory=dict)
    kind: str = ""
    default_asset: str = ""
    render: dict[str, Any] = field(default_factory=dict)
    expressions: dict[str, dict[str, Any]] = field(default_factory=dict)
    mouth_states: dict[str, int] = field(default_factory=dict)
    default_expression: str = ""
    default_mouth: str = ""
    motion_scripts: dict[str, Any] = field(default_factory=dict)
    level: int = 1                               # progression stat; everyone starts at 1
    revision: float = 1.0                        # definition version; bumps on edit (vs level)
    neutral: bool = False                        # see below — the no-persona default
    root: Path | None = None

    # ``neutral`` marks the sheet that is NOT a character: the ``assistant``
    # preset, a plain professional AI with no name, backstory, or affect of
    # its own. It is the one sheet whose name yields to the instance's own
    # (identity.yaml), because there is no one there to be — see
    # :func:`persona_display_name`. Every other sheet IS somebody, and that
    # somebody's name is the agent's name while it is active.

    @property
    def name(self) -> str:
        return self.personality.name or self.id

    @property
    def description(self) -> str:
        return self.personality.description

    def identity_block(self) -> str:
        """Concise 'who you are' — drives the identity prompt fragment."""
        return (f"You are {self.name}. {self.role}".strip()
                if self.role else f"You are {self.name}.")

    def _bullets(self, label: str, items: tuple[str, ...], quote: bool = False) -> str:
        if not items:
            return ""
        body = "\n".join((f'- "{x}"' if quote else f"- {x}") for x in items)
        return f"{label}:\n{body}"

    def soul_block(self) -> str:
        """The SHORT brief's narrative slice — just the soul narrative. The
        core directive and concise psychology are compiled separately.
        Signature quotes remain reference material so the model does not
        parrot catchphrases. This method owns only the soul narrative."""
        text = self.soul.strip()
        if not text:
            return ""
        try:
            from jaeger_ai.core.prompt_documents import SOUL_MAX_CHARS
            cap = int(SOUL_MAX_CHARS)
        except Exception:  # noqa: BLE001 — a missing cap must not break compose
            cap = 4_000
        if len(text) > cap:
            return text[:cap].rstrip() + "\n…(SOUL.md truncated)"
        return text

    def _lore_block(self) -> str:
        """Full in-depth lore for Studio and profile inspection."""
        parts = [
            self._bullets("Ideals", self.ideals),
            self._bullets("Mannerisms", self.mannerisms),
            self._bullets("Behaviors", self.behaviors),
            self._bullets("Speech patterns", tuple(self.personality.speech_patterns)),
            self._bullets("Signature lines", self.quotes, quote=True),
            ("Backstory: " + self.backstory.strip()) if self.backstory else "",
        ]
        return "\n\n".join(x for x in parts if x)

    def prompt(self) -> str:
        """Full IN-DEPTH persona for the Studio profile (directive + narrative +
        all lore). NOT what the live model sees — that's a short brief."""
        ci = self.personality.custom_instructions.strip()
        return "\n\n".join(x for x in (ci, self.soul.strip(), self._lore_block()) if x)

    def character_block(self) -> str:
        """The unified persona VIEW the live model sees — identity + soul +
        compiled trait clauses + the persona boundary, as one coherent block.

        This is the compiled View of the character's State (the numeric
        sliders). It replaces the old identity/soul/personality fragments.
        Compiled here, not on disk: the assembled prompt is cached and only
        rebuilt when the character sheet changes (main.py _refresh_character_
        prompt), so this runs on edit, not per turn. Main agent only — a
        sub-agent gets no persona (its preamble is its whole identity).
        See dev/docs/reality/persona_compiler.md."""
        from jaeger_ai.features.personality.compose import (
            PERSONA_BOUNDARY, disposition_clauses, domain_lens,
            expression_clauses,
        )
        p = self.personality
        parts: list[str] = [f"## My voice — {self.name}"]
        if self.role:
            parts.append(f"Role: {self.role.strip().rstrip('.')}.")
        # Persona body = the prose fields written for the model: soul (narrative)
        # + custom_instructions (the directive; per schema the one that feeds the
        # model today). `description` is a library tagline (UI only) and excluded;
        # the "You are X" one-liner is a last-resort fallback when there's no body
        # at all. The header already names the character, so a body never needs
        # the one-liner too — this is what kills the repeated "You are X".
        body = [x.strip() for x in (self.soul_block(), p.custom_instructions) if x.strip()]
        parts.extend(body or [self.identity_block()])
        # A preset is a complete baseline, so the fields an author supplied
        # must reach the live character view. Quotes remain reference/eval
        # material: feeding catchphrases encourages parroting rather than a
        # coherent person. Lists are capped to keep the 4B persona lane lean.
        psychology: list[str] = []
        if self.ideals:
            psychology.append("Core values: " + "; ".join(self.ideals[:4]) + ".")
        if self.behaviors:
            psychology.append(
                "Behavioral defaults: " + "; ".join(self.behaviors[:4]) + "."
            )
        if self.mannerisms:
            psychology.append(
                "Interpersonal style: " + "; ".join(self.mannerisms[:3]) + "."
            )
        disposition = disposition_clauses(p.hexaco)
        if disposition:
            psychology.append("Underlying disposition: " + "; ".join(disposition) + ".")
        if self.backstory:
            context = self.backstory.strip()
            if len(context) > 320:
                context = context[:320].rsplit(" ", 1)[0].rstrip() + "…"
            psychology.append("Formative context: " + context)
        if psychology:
            parts.append("## Character psychology\n" + "\n".join(psychology))

        # Compiled expression View — deviations only — plus domain lens.
        voice: list[str] = []
        clauses = expression_clauses(p.expression)
        if clauses:
            voice.append("When you speak to the operator, " + ", ".join(clauses) + ".")
        lens = domain_lens(p.domains)
        if lens:
            voice.append(lens)
        if p.speech_patterns:
            voice.append("Speech habits: " + "; ".join(s for s in p.speech_patterns if s) + ".")
        if voice:
            parts.append(" ".join(voice))
        parts.append(PERSONA_BOUNDARY)
        return "\n\n".join(parts)

    def card_path(self) -> Path | None:
        if self.root and self.card:
            p = self.root / self.card
            return p if p.exists() else None
        return None

    def icon_path(self) -> Path | None:
        """Square profile icon for tray / menus / small avatars. Uses a dedicated
        ``icon`` asset when the character ships one, else falls back to the card
        art. Add ``assets/icon.png`` + an ``icon`` manifest entry for a tighter
        crop; until then the card serves."""
        return self.asset("icon") or self.card_path()

    def asset(self, role: str) -> Path | None:
        """Resolve a manifest asset by ROLE (e.g. 'model', 'idle', 'sprites') —
        the character's own ``assets/`` first, then the shared jaeger_ai/assets/
        library. Returns a Path or None. Nodes call this so they never hardcode
        a filename: ``character.asset('idle')``."""
        rel = _asset_reference(self.assets.get(role))
        return self._resolve_asset(rel) if rel else None

    def asset_dir(self, role: str) -> Path | None:
        """Like :meth:`asset`, for a manifest entry that names a directory."""
        return self.asset(role)

    def _resolve_asset(self, rel: str) -> Path | None:
        if self.root is not None:
            p = self.root / rel
            if p.exists():
                return p
        shared = shared_assets_dir() / rel
        return shared if shared.exists() else None


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 — unreadable files read as absent
        return ""


def _lore_lines(path: Path) -> tuple[str, ...]:
    text = _read_text_file(path)
    if not text:
        return ()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-").strip()
        if line:
            out.append(line)
    return tuple(out)


def _load_soul_text(folder: Path, yaml_soul: str) -> str:
    """Prefer ``SOUL.md`` as the live identity text; yaml is fallback."""
    for name in ("SOUL.md", "soul.md"):
        text = _read_text_file(folder / name)
        if text:
            return text
    return (yaml_soul or "").strip()


def _load_lore_field(folder: Path, filename: str, yaml_items: Any) -> tuple[str, ...]:
    packed = _lore_lines(folder / "lore" / filename)
    if packed:
        return packed
    return tuple(yaml_items or ())


def load_character(folder: Path) -> Character:
    """Load ``<folder>/character.yaml`` → a :class:`Character`."""
    folder = Path(folder)
    data = yaml.safe_load((folder / "character.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{folder / 'character.yaml'}: manifest must be a mapping")
    schema = data.get("schema")
    if schema not in (None, CHARACTER_SCHEMA):
        raise ValueError(
            f"{folder / 'character.yaml'}: schema must be {CHARACTER_SCHEMA!r}, "
            f"got {schema!r}"
        )
    ident = data.get("identity", {}) or {}
    pr = data.get("prompt", {}) or {}
    tr = data.get("traits", {}) or {}
    assets = data.get("assets", {}) or {}
    personality = Personality(
        name=data.get("name", folder.name),
        description=data.get("description", ""),
        custom_instructions=pr.get("custom_instructions", ""),
        speech_patterns=tuple(pr.get("speech_patterns", []) or ()),
        hexaco=_layer(HEXACO, tr.get("hexaco", {})),
        special=_layer(SPECIAL, tr.get("special", {})),
        expression=_layer(Expression, tr.get("expression", {})),
        domains=_layer(Domains, tr.get("domains", {})),
    )
    lore = data.get("lore", {}) or {}
    lore_dir = folder / "lore"
    backstory = _read_text_file(lore_dir / "backstory.md") or pr.get("backstory", "")
    return Character(
        # ``id`` was Jaeger AI's pre-standard spelling. It remains a read-only
        # compatibility alias; writers and bundled packs use ``character``.
        id=data.get("character") or data.get("id") or folder.name,
        personality=personality,
        version=str(data.get("version", "0.0.0")),
        author=str(data.get("author", "")),
        license=str(data.get("license", "Unspecified")),
        role=ident.get("role", ""),
        voice_tone=ident.get("voice_tone", ""),
        voice_id=ident.get("voice_id", "af_heart"),
        backstory=backstory,
        soul=_load_soul_text(folder, pr.get("soul", "")),
        quotes=_load_lore_field(folder, "quotes.md", lore.get("quotes", [])),
        mannerisms=_load_lore_field(folder, "mannerisms.md", lore.get("mannerisms", [])),
        ideals=_load_lore_field(folder, "ideals.md", lore.get("ideals", [])),
        behaviors=_load_lore_field(folder, "behaviors.md", lore.get("behaviors", [])),
        card=str(data.get("card") or _asset_reference(assets.get("card"))
                 or _asset_reference(assets.get(data.get("default_asset", "primary"))) or ""),
        avatar_dir=_asset_reference(assets.get("avatar")) or "avatar",
        assets=assets,
        kind=str(data.get("kind", "")),
        default_asset=str(data.get("default_asset", "")),
        render=dict(data.get("render") or {}),
        expressions=dict(data.get("expressions") or {}),
        mouth_states=dict(data.get("mouth_states") or {}),
        default_expression=str(data.get("default_expression", "")),
        default_mouth=str(data.get("default_mouth", "")),
        motion_scripts=dict(data.get("motion_scripts") or {}),
        level=int(data.get("level", 1) or 1),
        revision=float(data.get("revision", 1.0) or 1.0),
        neutral=bool(data.get("neutral", False)),
        root=folder,
    )


def shared_assets_dir() -> Path:
    """The shared asset library — ``jaeger_ai/assets/``. A character's own assets
    win; this is the fallback so common/generic assets aren't copied per
    character (mirrors the avatar tool's character-first resolution)."""
    return Path(__file__).resolve().parents[2] / "assets"


def characters_root() -> Path:
    """The bundled character library — ``characters/``."""
    return Path(__file__).resolve().parent / "characters"


def list_characters(root: Path | None = None) -> list[Character]:
    """Every character folder under ``root`` (default: the bundled library),
    sorted with neutral/default characters first, then alphabetically by name.
    Skips folders without a character.yaml."""
    root = Path(root) if root else characters_root()
    out: list[Character] = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "character.yaml").exists():
            try:
                out.append(load_character(d))
            except Exception:  # noqa: BLE001,S112 — one bad sheet cannot break library
                continue
    return sorted(out, key=lambda c: (not c.neutral, c.name.lower()))


# msgspec struct -> dict, for the profile UI to iterate trait sliders.
def layer_items(struct: Any) -> list[tuple[str, float]]:
    return list(msgspec.structs.asdict(struct).items())


# ── active character (which character an instance plays) ────────────
_ACTIVE_FILE = "active_character"
# ponytail: every instance ALWAYS plays a character — there is no "no persona"
# state. An instance that hasn't picked one plays the default.
#
# That default is the NEUTRAL sheet (2026-08-19). It used to be ``jarvis``,
# which was invisible while a character's name could never reach the model
# — and became load-bearing the moment it could: an operator who had never
# opened the character picker got an agent that introduced itself as
# Jarvis. A fresh instance is now a plain assistant answering to its own
# name, and becomes somebody else only when the operator says so.
DEFAULT_CHARACTER_ID = "assistant"


def active_character_id(instance_root: Path) -> str:
    """The character this instance plays right now. Never empty — falls back to
    the instance's BOUND (canonical) character, then DEFAULT_CHARACTER_ID. So a
    bound unit defaults to its own persona even if the active file is cleared."""
    f = Path(instance_root) / _ACTIVE_FILE
    cid = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    return cid or bound_character_id(instance_root) or DEFAULT_CHARACTER_ID


def bound_character_id(instance_root: Path) -> str:
    """The character this instance is BOUND to — its canonical identity, written
    to manifest.json at creation and changed only by an explicit rebind. Empty
    string if the instance is unbound (a free-swap dev box)."""
    f = Path(instance_root) / "manifest.json"
    if not f.exists():
        return ""
    try:
        import json
        return (json.loads(f.read_text(encoding="utf-8")).get("bound_character") or "").strip()
    except Exception:  # noqa: BLE001 — a missing/garbled manifest is just "unbound"
        return ""


def bind_character(instance_root: Path, cid: str) -> None:
    """Rebind the instance to ``cid`` — the deliberate, verified change. Rewrites
    manifest.json's bound_character (the canonical identity) AND sets it active.
    A plain :func:`set_active_character` is only a session-level override; this
    moves the binding. Memory + skill XP live in the instance, so they survive."""
    import json
    import os
    root = Path(instance_root)
    f = root / "manifest.json"
    doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    doc["bound_character"] = cid.strip()
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.replace(tmp, f)
    set_active_character(root, cid)


def active_character_signature(instance_root: Path) -> str:
    """id + sheet mtime + runtime-override mtime — changes when the
    character switches, when its sheet is edited, or when this instance
    adapts a trait, so instant-apply rebuilds the prompt for all three."""
    from jaeger_ai.features.personality import persona_state
    cid = active_character_id(instance_root)
    try:
        mt = (characters_root() / cid / "character.yaml").stat().st_mtime
    except OSError:
        mt = 0.0
    return f"{cid}:{mt}:{persona_state.signature(instance_root)}"


def set_active_character(instance_root: Path, cid: str) -> None:
    """Set the character this instance plays (writes <instance>/active_character)."""
    root = Path(instance_root); root.mkdir(parents=True, exist_ok=True)
    (root / _ACTIVE_FILE).write_text(cid.strip(), encoding="utf-8")


def active_character(instance_root: Path) -> Character | None:
    """The character this instance plays — the agent's real persona; its prompt
    REPLACES the instance persona files (see jaeger_agent/prompts/). Falls
    back to the default character if the picked one is missing or broken, so a
    running agent always has a persona. None only if no character loads at all.

    The sheet is the DEFINITION; this instance's runtime overrides
    (``persona_state.yaml`` — what ``adjust_trait`` learned) are applied
    on top. The definition file itself is never written by the runtime,
    so the same character stays identical for every other instance
    playing it. See :mod:`jaeger_ai.features.personality.persona_state`."""
    from jaeger_ai.features.personality import persona_state
    for cid in (active_character_id(instance_root), DEFAULT_CHARACTER_ID):
        folder = characters_root() / cid
        if (folder / "character.yaml").exists():
            try:
                character = load_character(folder)
            except Exception:  # noqa: BLE001
                continue
            try:
                persona_state.apply_overrides(
                    character,
                    persona_state.load_overrides(instance_root, character.id),
                )
            except Exception:  # noqa: BLE001 — overrides are optional
                pass
            return character
    return None


def persona_display_name(agent_name: str, character: Any) -> str:
    """The ONE name the agent answers to right now.

    Operator decision, 2026-08-19 — reversing the 2026-07-05 framing that
    let the instance name override the character's everywhere. That rule
    produced a two-headed agent: the prompt said "you are Ted, modeled on
    Clanker, never call yourself Clanker", and the surfaces said "Ted
    playing Clanker". Asked who it was, the model had two identities to
    pick from and picked badly. There is now exactly one:

      * a character sheet is SOMEBODY — while it is active, its name IS
        the agent's name, in the prompt and on every surface;
      * the ``neutral`` sheet (``assistant``) is nobody in particular, so
        the instance's own name (identity.yaml) comes through — that is
        the sheet to pick to be "Ted, a plain assistant".

    ``agent_name`` is identity.yaml's name; ``character`` may be None.
    Falls back to whichever of the two exists.
    """
    agent_name = (agent_name or "").strip()
    if character is None:
        return agent_name
    if getattr(character, "neutral", False):
        return agent_name or str(getattr(character, "name", "") or "")
    return str(getattr(character, "name", "") or "") or agent_name


def save_character_traits(folder: Path, traits: dict) -> None:
    """Write edited trait layers back to <folder>/character.yaml (the Studio
    trait editor). Only the four trait layers are touched."""
    yf = Path(folder) / "character.yaml"
    doc = yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
    t = doc.setdefault("traits", {})
    for layer in ("hexaco", "special", "expression", "domains"):
        if layer in traits:
            t[layer] = {k: round(float(v), 3) for k, v in traits[layer].items()}
    # An edit is a new revision — bump the definition version (level is separate).
    doc["revision"] = round(float(doc.get("revision", 1.0) or 1.0) + 0.1, 1)
    yf.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def save_character_profile(folder: Path, *, role: str | None = None,
                           voice_tone: str | None = None, voice_id: str | None = None,
                           soul: str | None = None, backstory: str | None = None,
                           custom_instructions: str | None = None) -> None:
    """Write edited identity/prompt fields back to <folder>/character.yaml.

    Companion to :func:`save_character_traits` — that one owns the trait layers,
    this one owns the narrative + identity. Only non-None fields are touched;
    bumps ``revision`` so the running agent re-reads the persona next turn."""
    yf = Path(folder) / "character.yaml"
    doc = yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
    ident = doc.setdefault("identity", {})
    prompt = doc.setdefault("prompt", {})
    if role is not None:
        ident["role"] = role
    if voice_tone is not None:
        ident["voice_tone"] = voice_tone
    if voice_id is not None:
        ident["voice_id"] = voice_id
    if soul is not None:
        soul_md = Path(folder) / "SOUL.md"
        if soul_md.exists() or (Path(folder) / "soul.md").exists():
            target = soul_md if soul_md.exists() else (Path(folder) / "soul.md")
            target.write_text(soul.strip() + ("\n" if soul.strip() else ""), encoding="utf-8")
        else:
            prompt["soul"] = soul
    if backstory is not None:
        prompt["backstory"] = backstory
    if custom_instructions is not None:
        prompt["custom_instructions"] = custom_instructions
    doc["revision"] = round(float(doc.get("revision", 1.0) or 1.0) + 0.1, 1)
    yf.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def generate_card(folder: Path, name: str) -> str:
    """Write a placeholder profile card (distinct color + initial + name).
    Returns the relative path used by the sheet's top-level ``card`` field."""
    import colorsys
    import hashlib

    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    def _font(sz: int):
        for fp in ("/System/Library/Fonts/Helvetica.ttc",
                   "/System/Library/Fonts/Supplemental/Arial.ttf"):
            try:
                return ImageFont.truetype(fp, sz)
            except Exception:  # noqa: BLE001,S110 — try the next platform font
                pass
        return ImageFont.load_default()
    W, H = 320, 420
    hue = (int(hashlib.md5(name.encode()).hexdigest(), 16) % 360) / 360.0
    top = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 0.45, 0.55)]
    bot = [int(x * 255) for x in colorsys.hsv_to_rgb(hue, 0.6, 0.10)]
    arr = np.zeros((H, W, 3), np.uint8)
    for i in range(3):
        arr[:, :, i] = np.linspace(top[i], bot[i], H).astype(np.uint8).reshape(H, 1)
    img = Image.fromarray(arr); dr = ImageDraw.Draw(img)
    cx, cy, r = W // 2, 150, 72
    dr.ellipse([cx - r, cy - r, cx + r, cy + r],
               fill=tuple(int(x * 255) for x in colorsys.hsv_to_rgb(hue, 0.30, 0.92)))
    fi = _font(86); ini = (name[:1] or "?").upper()
    bb = dr.textbbox((0, 0), ini, font=fi)
    dr.text((cx - (bb[2] - bb[0]) / 2 - bb[0], cy - (bb[3] - bb[1]) / 2 - bb[1]), ini, fill=(22, 18, 32), font=fi)
    fn = _font(26); bb = dr.textbbox((0, 0), name, font=fn)
    if bb[2] - bb[0] > W - 28:
        fn = _font(19); bb = dr.textbbox((0, 0), name, font=fn)
    dr.text(((W - (bb[2] - bb[0])) / 2 - bb[0], 280), name, fill=(255, 255, 255), font=fn)
    img.save(Path(folder) / "card.png")
    return "card.png"


def create_character(name: str, *, role: str = "", custom_instructions: str = "",
                     root: Path | None = None) -> Character:
    """Create a new character folder + sheet (default traits) + a card."""
    import re
    cid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "character"
    base = Path(root) if root else characters_root()
    folder = base / cid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "avatar").mkdir(exist_ok=True)
    card = generate_card(folder, name)
    doc = {
        "schema": CHARACTER_SCHEMA, "character": cid, "name": name,
        "version": "0.1.0", "author": "Jenkins Robotics",
        "license": "Unspecified", "description": "",
        "kind": "clip_set",
        "assets": {
            "primary": {"file": card, "type": "image", "adapter": "image"},
        },
        "default_asset": "primary",
        "render": {"adapter": "image", "asset": card,
                   "ideal_size": [320, 420], "framing": "fit",
                   "scaling": "smooth"},
        "expressions": {"idle": {"clips": card, "loop": False}},
        "default_expression": "idle", "default_mouth": "",
        "card": card,
        "identity": {"role": role, "voice_tone": "", "voice_id": "af_heart"},
        "prompt": {"custom_instructions": custom_instructions, "soul": "",
                   "backstory": "", "speech_patterns": []},
        "traits": {}, "lore": {"quotes": [], "mannerisms": [], "ideals": [], "behaviors": []},
        "level": 1, "revision": 1.0,
    }
    (folder / "character.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return load_character(folder)
