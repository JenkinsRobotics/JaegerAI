"""Data-only scene declarations inside character/v1 render.scene.

Only declared, contained media files are exposed. No pack-supplied scripts run
in the operator's authenticated UI. Renderers consume URLs, never disk paths.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from .character import Character, _asset_reference

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm"}


def scene_asset(character: Character, key: str) -> Path | None:
    if not character.root or not re.fullmatch(r"[\w-]{1,80}", key):
        return None
    rel = _asset_reference(character.assets.get(key))
    if not rel or Path(rel).is_absolute():
        return None
    root = character.root.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in MEDIA or not path.is_file():
        return None
    if MEDIA[path.suffix.lower()].startswith("image/"):
        # Animated image tags cannot be reliably paused. Motion packs use
        # controllable video; static images remain safe under reduced motion.
        from PIL import Image
        try:
            with Image.open(path) as image:
                if getattr(image, "is_animated", False):
                    return None
        except (OSError, ValueError):
            return None
    return path


def scene_presentation(character: Character) -> dict:
    raw = character.render.get("scene", {})
    raw = raw if isinstance(raw, dict) else {}
    base = f"/v1/characters/{quote(character.id, safe='')}/scene/assets/"
    layout = raw.get("layout")

    def media(key):
        path = scene_asset(character, key) if isinstance(key, str) else None
        if path is None:
            return None
        return {"url": base + quote(key, safe=""),
                "type": "video" if MEDIA[path.suffix.lower()].startswith("video/") else "image"}

    actions = {}
    for action, key in (raw.get("actions", {}) if isinstance(raw.get("actions"), dict) else {}).items():
        if isinstance(action, str) and re.fullmatch(r"[a-z_]{1,40}", action):
            if item := media(key):
                actions[action] = item
    return {
        "version": 1,
        "character_id": character.id,
        "layout": layout if isinstance(layout, str) and layout in {"portrait", "desk", "workbench"} else "portrait",
        "background": media(raw.get("background")),
        "portrait": media("icon") or media("primary") or media("card"),
        "actions": actions,
    }
