"""Character — a library preset on top of :class:`Personality`.

``personality/`` IS the character logic: :mod:`schema` holds the trait model
(HEXACO/SPECIAL/Expression/Domains + custom_instructions) and :mod:`compose`
renders it into the system prompt. A *character* is just that ``Personality``
plus the library extras — identity (role/voice), backstory, and assets
(card/avatar) — stored as a folder ``personality/characters/<id>/``.

Only ``custom_instructions`` feeds the model today; the trait ratings are
stored + shown on the profile and drive behavior in a later update.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import msgspec
import yaml

from jaeger_os.personality.schema import (
    HEXACO, SPECIAL, Domains, Expression, Personality,
)


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
    assets: dict = field(default_factory=dict)   # manifest: role -> relative path
    level: int = 1                               # progression stat; everyone starts at 1
    revision: float = 1.0                        # definition version; bumps on edit (vs level)
    root: Path | None = None

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
        core directive + traits come from the personality block (compose_block).
        The rich lore (ideals/mannerisms/quotes/...) stays on the sheet for
        future use and is NOT dumped into the live prompt — keeps turns lean.
        ponytail: brief today; sheet is the in-depth store for later."""
        return self.soul.strip()

    def _lore_block(self) -> str:
        """In-depth lore — Studio display + future use, never the live prompt."""
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
        the character's own ``assets/`` first, then the shared jaeger_os/assets/
        library. Returns a Path or None. Nodes call this so they never hardcode
        a filename: ``character.asset('idle')``."""
        rel = self.assets.get(role)
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


def load_character(folder: Path) -> Character:
    """Load ``<folder>/character.yaml`` → a :class:`Character`."""
    folder = Path(folder)
    data = yaml.safe_load((folder / "character.yaml").read_text(encoding="utf-8")) or {}
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
    return Character(
        id=data.get("id", folder.name),
        personality=personality,
        role=ident.get("role", ""),
        voice_tone=ident.get("voice_tone", ""),
        voice_id=ident.get("voice_id", "af_heart"),
        backstory=pr.get("backstory", ""),
        soul=pr.get("soul", ""),
        quotes=tuple(lore.get("quotes", []) or ()),
        mannerisms=tuple(lore.get("mannerisms", []) or ()),
        ideals=tuple(lore.get("ideals", []) or ()),
        behaviors=tuple(lore.get("behaviors", []) or ()),
        card=assets.get("card", ""),
        avatar_dir=assets.get("avatar", "avatar"),
        assets=assets,
        level=int(data.get("level", 1) or 1),
        revision=float(data.get("revision", 1.0) or 1.0),
        root=folder,
    )


def shared_assets_dir() -> Path:
    """The shared asset library — ``jaeger_os/assets/``. A character's own assets
    win; this is the fallback so common/generic assets aren't copied per
    character (mirrors the avatar tool's character-first resolution)."""
    return Path(__file__).resolve().parent.parent / "assets"


def characters_root() -> Path:
    """The bundled character library — ``personality/characters/``."""
    return Path(__file__).resolve().parent / "characters"


def list_characters(root: Path | None = None) -> list[Character]:
    """Every character folder under ``root`` (default: the bundled library),
    sorted by name. Skips folders without a character.yaml."""
    root = Path(root) if root else characters_root()
    out: list[Character] = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "character.yaml").exists():
            try:
                out.append(load_character(d))
            except Exception:  # noqa: BLE001 — one bad sheet never breaks the library
                continue
    return sorted(out, key=lambda c: c.name.lower())


# msgspec struct -> dict, for the profile UI to iterate trait sliders.
def layer_items(struct: Any) -> list[tuple[str, float]]:
    return list(msgspec.structs.asdict(struct).items())


# ── active character (which character an instance plays) ────────────
_ACTIVE_FILE = "active_character"
# ponytail: every instance ALWAYS plays a character — there is no "no persona"
# state. An instance that hasn't picked one plays the default.
DEFAULT_CHARACTER_ID = "jarvis"


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
    """id + sheet mtime — changes when the character switches OR its traits are
    edited, so instant-apply rebuilds the prompt for both."""
    cid = active_character_id(instance_root)
    try:
        mt = (characters_root() / cid / "character.yaml").stat().st_mtime
    except OSError:
        mt = 0.0
    return f"{cid}:{mt}"


def set_active_character(instance_root: Path, cid: str) -> None:
    """Set the character this instance plays (writes <instance>/active_character)."""
    root = Path(instance_root); root.mkdir(parents=True, exist_ok=True)
    (root / _ACTIVE_FILE).write_text(cid.strip(), encoding="utf-8")


def active_character(instance_root: Path) -> "Character | None":
    """The character this instance plays — the agent's real persona; its prompt
    REPLACES the instance persona files (see agent/prompts/assemble.py). Falls
    back to the default character if the picked one is missing or broken, so a
    running agent always has a persona. None only if no character loads at all."""
    for cid in (active_character_id(instance_root), DEFAULT_CHARACTER_ID):
        folder = characters_root() / cid
        if (folder / "character.yaml").exists():
            try:
                return load_character(folder)
            except Exception:  # noqa: BLE001
                continue
    return None


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
        prompt["soul"] = soul
    if backstory is not None:
        prompt["backstory"] = backstory
    if custom_instructions is not None:
        prompt["custom_instructions"] = custom_instructions
    doc["revision"] = round(float(doc.get("revision", 1.0) or 1.0) + 0.1, 1)
    yf.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def generate_card(folder: Path, name: str) -> str:
    """Write a placeholder profile card (distinct color + initial + name).
    Returns the relative path written into the sheet's assets.card."""
    import colorsys, hashlib
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    def _font(sz: int):
        for fp in ("/System/Library/Fonts/Helvetica.ttc",
                   "/System/Library/Fonts/Supplemental/Arial.ttf"):
            try:
                return ImageFont.truetype(fp, sz)
            except Exception:
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
                     root: Path | None = None) -> "Character":
    """Create a new character folder + sheet (default traits) + a card."""
    import re
    cid = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "character"
    base = Path(root) if root else characters_root()
    folder = base / cid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "avatar").mkdir(exist_ok=True)
    card = generate_card(folder, name)
    doc = {
        "schema": "character/v1", "id": cid, "name": name, "description": "",
        "identity": {"role": role, "voice_tone": "", "voice_id": "af_heart"},
        "prompt": {"custom_instructions": custom_instructions, "soul": "",
                   "backstory": "", "speech_patterns": []},
        "traits": {}, "lore": {"quotes": [], "mannerisms": [], "ideals": [], "behaviors": []},
        "assets": {"card": card, "avatar": "avatar"},
    }
    (folder / "character.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return load_character(folder)
