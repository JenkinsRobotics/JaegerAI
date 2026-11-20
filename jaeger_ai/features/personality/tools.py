"""Agent tool for summoning an Avatar-style Character Council with Truth synthesis.

Summoned characters run strictly with scoped CompanionMemory and zero access to
private user execution tools; Truth evaluates their contrasting perspectives
against evidence below the persona layer.
"""
from __future__ import annotations

from typing import Any

from .character import characters_root, list_characters, load_character
from .companion import CompanionError, CompanionMemory, council_chat


def summon_council(
    characters: list[str],
    topic: str,
    include_truth_synthesis: bool = True,
    model: str = "",
    *,
    memory: CompanionMemory | None = None,
    post: Any = None,
) -> dict[str, Any]:
    """Consult 2-6 characters on a topic with isolated memory and optional Truth synthesis."""
    if not isinstance(characters, list) or len(characters) < 2 or len(characters) > 6:
        available = [c.id for c in list_characters(characters_root())]
        return {
            "ok": False,
            "error": "characters must be a list of 2 to 6 character IDs",
            "available_characters": available,
        }
    root = characters_root().resolve()
    loaded = []
    missing = []
    for raw_id in characters:
        cid = str(raw_id or "").strip()
        folder = (root / cid).resolve()
        if not cid or not folder.is_relative_to(root) or folder == root or not (folder / "character.yaml").is_file():
            missing.append(cid)
        else:
            loaded.append(load_character(folder))
    if missing:
        available = [c.id for c in list_characters(root)]
        return {
            "ok": False,
            "error": f"unknown character ID(s): {', '.join(missing)}",
            "available_characters": available,
        }
    mem = memory if memory is not None else CompanionMemory()
    try:
        out = council_chat(
            loaded,
            topic,
            memory=mem,
            model=(model or "").strip() or None,
            include_truth_synthesis=bool(include_truth_synthesis),
            post=post,
        )
        return {"ok": True, **out}
    except CompanionError as exc:
        return {"ok": False, "error": str(exc), "status": exc.status}
