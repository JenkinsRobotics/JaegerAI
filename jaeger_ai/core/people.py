"""Person index — profiles of the people the agent INTERACTS with.

Distinct from CHARACTERS (``personality/characters/`` — personalities the agent
*plays*): a *person* is someone the agent *knows* — the owner, a guest on a
channel — with their name, channel handles, access level, likes, and learned
facts. The agent builds + expands these over time the way it grows skills.

One YAML per person at ``<instance>/people/<id>.yaml`` — editable, inspectable,
and a structured corpus for future personalization / training. ``access`` is
the trust level (admin / member / blocked); a person marked ``admin`` whose
handles include a channel id is treated as the owner there (see
``admins_for_channel``), so the person index is the single source of truth for
"who is who" and "what they're allowed to do".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ACCESS_LEVELS = ("admin", "member", "blocked")


@dataclass
class Person:
    id: str = ""
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    # channel → ids that are THIS person, e.g. {"telegram": ["8777030623"]}
    handles: dict[str, list[str]] = field(default_factory=dict)
    access: str = "member"            # admin | member | blocked
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    notes: str = ""
    facts: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "person"


def people_dir(layout: Any) -> Path:
    return Path(layout.root) / "people"


def _from_dict(d: dict) -> Person:
    known = set(Person.__dataclass_fields__)
    return Person(**{k: v for k, v in (d or {}).items() if k in known})


def load_person(layout: Any, person_id: str) -> Person | None:
    p = people_dir(layout) / f"{person_id}.yaml"
    if not p.exists():
        return None
    try:
        return _from_dict(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    except Exception:  # noqa: BLE001 — a broken profile never breaks the index
        return None


def save_person(layout: Any, person: Person) -> Path:
    d = people_dir(layout)
    d.mkdir(parents=True, exist_ok=True)
    person.updated_at = _now()
    if not person.created_at:
        person.created_at = person.updated_at
    path = d / f"{person.id}.yaml"
    path.write_text(yaml.safe_dump(asdict(person), sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return path


def list_people(layout: Any) -> list[Person]:
    d = people_dir(layout)
    if not d.exists():
        return []
    out: list[Person] = []
    for f in sorted(d.glob("*.yaml")):
        person = load_person(layout, f.stem)
        if person is not None:
            out.append(person)
    return out


def find_by_name(layout: Any, name: str) -> Person | None:
    """Resolve a person by id, exact name, or alias (case-insensitive)."""
    q = (name or "").strip().lower()
    if not q:
        return None
    direct = load_person(layout, slugify(name))
    if direct is not None:
        return direct
    for person in list_people(layout):
        if person.name.lower() == q or q in [a.lower() for a in person.aliases]:
            return person
    return None


def find_by_handle(layout: Any, channel: str, handle: str) -> Person | None:
    """Who is this channel account? e.g. find_by_handle(l, 'telegram', '8777…')."""
    handle = str(handle).strip()
    for person in list_people(layout):
        if handle in [str(h) for h in person.handles.get(channel, [])]:
            return person
    return None


def admins_for_channel(layout: Any, channel: str) -> set[str]:
    """Every handle on ``channel`` belonging to a person with ``access=admin`` —
    the owner's certified accounts, fed into a bridge's admin set on activation."""
    out: set[str] = set()
    for person in list_people(layout):
        if person.access == "admin":
            out.update(str(h) for h in person.handles.get(channel, []))
    return out


def upsert_person(layout: Any, *, name: str, access: str | None = None,
                  channel: str = "", handle: str = "", like: str = "",
                  note: str = "") -> Person:
    """Create a person (by name) or merge fields into the existing profile —
    the agent's build-it-as-you-learn entry point. Lists are appended (deduped);
    access is set; a channel+handle pair is linked."""
    person = find_by_name(layout, name) or Person(id=slugify(name), name=name.strip())
    if not person.id:
        person.id = slugify(name)
    if not person.name:
        person.name = name.strip()
    if access in ACCESS_LEVELS:
        person.access = access
    if channel and handle:
        ids = person.handles.setdefault(channel, [])
        if str(handle) not in [str(h) for h in ids]:
            ids.append(str(handle))
    if like and like not in person.likes:
        person.likes.append(like)
    if note and note not in person.facts:
        person.facts.append(note)
    save_person(layout, person)
    return person
