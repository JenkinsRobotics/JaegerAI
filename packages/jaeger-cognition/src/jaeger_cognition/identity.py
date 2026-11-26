"""User-configurable Digital Counterpart Identity & Character Overlays (Directive §2).

Zero hardcoded founder identity: every installation stores its own AI name,
owner profile, voice, avatar preset, objectives, and channels in
``<state_dir>/identity.json``. Summonable Characters change expressive style
and voice without ever replacing the singular intelligence, erasing memory,
or disabling truthfulness.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CharacterOverlay:
    character_id: str
    name: str
    style: str
    voice_id: str = ""
    avatar_preset: str = "studio_cel"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IdentityProfile:
    ai_name: str = "Jaeger"
    owner_name: str = "Owner"
    voice_id: str = "af_heart"
    avatar_mode: str = "2d_character"
    personality: str = "Calm, evidence-seeking, proactive, honest, and supportive of human growth."
    mission: str = "Help my owner achieve their goals, build real work, and flourish independently."
    objectives: list[str] = field(default_factory=list)
    channels: list[dict[str, str]] = field(default_factory=list)
    active_character_id: str | None = None
    characters: dict[str, dict[str, Any]] = field(default_factory=dict)
    privacy_local_first: bool = True
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IdentityStore:
    """Durable user-owned identity store at ``<state_dir>/identity.json``."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "identity.json"
        self._lock = threading.RLock()
        if not self._path.is_file():
            self._save_locked(IdentityProfile(updated_at=time.time()))

    def _load_locked(self) -> IdentityProfile:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return IdentityProfile(updated_at=time.time())
        if not isinstance(raw, dict):
            return IdentityProfile(updated_at=time.time())
        return IdentityProfile(
            ai_name=str(raw.get("ai_name") or "Jaeger"),
            owner_name=str(raw.get("owner_name") or "Owner"),
            voice_id=str(raw.get("voice_id") or "af_heart"),
            avatar_mode=str(raw.get("avatar_mode") or "2d_character"),
            personality=str(raw.get("personality") or IdentityProfile.personality),
            mission=str(raw.get("mission") or IdentityProfile.mission),
            objectives=list(raw.get("objectives") or []),
            channels=list(raw.get("channels") or []),
            active_character_id=raw.get("active_character_id") or None,
            characters=dict(raw.get("characters") or {}),
            privacy_local_first=bool(raw.get("privacy_local_first", True)),
            updated_at=float(raw.get("updated_at") or time.time()),
        )

    def _save_locked(self, profile: IdentityProfile) -> None:
        profile.updated_at = time.time()
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def get(self) -> IdentityProfile:
        with self._lock:
            return self._load_locked()

    def update(self, **changes: Any) -> IdentityProfile:
        with self._lock:
            p = self._load_locked()
            for field_name in (
                "ai_name",
                "owner_name",
                "voice_id",
                "avatar_mode",
                "personality",
                "mission",
                "objectives",
                "channels",
                "privacy_local_first",
            ):
                if field_name in changes and changes[field_name] is not None:
                    setattr(p, field_name, changes[field_name])
            self._save_locked(p)
            return p

    def upsert_character(self, overlay: CharacterOverlay, *, activate: bool = False) -> IdentityProfile:
        with self._lock:
            p = self._load_locked()
            p.characters[overlay.character_id] = overlay.to_dict()
            if activate:
                p.active_character_id = overlay.character_id
            self._save_locked(p)
            return p

    def set_active_character(self, character_id: str | None) -> IdentityProfile:
        with self._lock:
            p = self._load_locked()
            if character_id and character_id not in p.characters:
                raise KeyError(f"Unknown character: {character_id}")
            p.active_character_id = character_id or None
            self._save_locked(p)
            return p

    def compile_system_prompt(self) -> str:
        """Compile active identity + optional character overlay with truthfulness invariant."""
        p = self.get()
        lines = [
            f"You are {p.ai_name}, a persistent, local-first personal intelligence partnering with {p.owner_name}.",
            f"Mission: {p.mission}",
            f"Style: {p.personality}",
            "Truthfulness invariant: Always distinguish verified observations/tool outputs from assumptions, report failures honestly, and never claim an action succeeded without verifying the actual result.",
        ]
        if p.objectives:
            lines.append("Active owner objectives: " + "; ".join(p.objectives[:6]))
        if p.active_character_id and p.active_character_id in p.characters:
            ch = p.characters[p.active_character_id]
            lines.append(
                f"Active expressive character overlay: {ch.get('name')} — {ch.get('style')} "
                "(This is an expressive overlay only; retain full memory, continuity, and truthfulness.)"
            )
        return "\n".join(lines)


__all__ = ["CharacterOverlay", "IdentityProfile", "IdentityStore"]
