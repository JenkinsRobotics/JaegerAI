"""
ARES SI — Structured user model.

Facts about the user with provenance and confidence.
Stored in ~/.ares/si/user_model.json — human-readable, editable.

Key rule: inferred facts never auto-promote above 0.7 confidence.
Only explicit_user_instruction facts get 1.0.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import DataClassification, PERSONAL


def _user_model_path() -> Path:
    ares_home = os.environ.get("ARES_HOME", os.path.expanduser("~/.ares"))
    si_dir = Path(ares_home) / "si"
    si_dir.mkdir(parents=True, exist_ok=True)
    return si_dir / "user_model.json"


@dataclass
class UserFact:
    """A single fact about the user, with provenance and confidence."""
    fact_id: str
    fact: str
    source: str = "observed_behavior"  # explicit_user_instruction, observed_behavior, inferred
    confidence: float = 0.5
    sensitivity: str = "personal"
    category: str = ""                 # preference, project, person, device, routine
    editable: bool = True
    created_at: float = 0.0
    last_confirmed_at: float | None = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        # Enforce confidence caps
        if self.source == "inferred" and self.confidence > 0.7:
            self.confidence = 0.7
        if self.source == "explicit_user_instruction":
            self.confidence = 1.0


@dataclass
class UserModel:
    """Structured, editable model of the user."""
    preferences: list[UserFact] = field(default_factory=list)
    projects: list[UserFact] = field(default_factory=list)
    people: list[UserFact] = field(default_factory=list)
    devices: list[UserFact] = field(default_factory=list)
    routines: list[UserFact] = field(default_factory=list)
    privacy_preferences: list[UserFact] = field(default_factory=list)
    restrictions: list[UserFact] = field(default_factory=list)


def _serialize_fact(f: UserFact) -> dict:
    return {
        "fact_id": f.fact_id,
        "fact": f.fact,
        "source": f.source,
        "confidence": f.confidence,
        "sensitivity": f.sensitivity,
        "category": f.category,
        "editable": f.editable,
        "created_at": f.created_at,
        "last_confirmed_at": f.last_confirmed_at,
    }


def _deserialize_fact(d: dict) -> UserFact:
    return UserFact(
        fact_id=d.get("fact_id", f"fact_{int(time.time()*1000)}_{os.urandom(2).hex()}"),
        fact=d.get("fact", ""),
        source=d.get("source", "observed_behavior"),
        confidence=float(d.get("confidence", 0.5)),
        sensitivity=d.get("sensitivity", "personal"),
        category=d.get("category", ""),
        editable=bool(d.get("editable", True)),
        created_at=float(d.get("created_at", time.time())),
        last_confirmed_at=float(d["last_confirmed_at"]) if d.get("last_confirmed_at") else None,
    )


def load_user_model() -> UserModel:
    """Load the user model from disk, or return empty defaults."""
    path = _user_model_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return UserModel()

    if not isinstance(data, dict):
        return UserModel()

    def load_category(key: str) -> list[UserFact]:
        items = data.get(key, [])
        if not isinstance(items, list):
            return []
        return [_deserialize_fact(item) for item in items if isinstance(item, dict)]

    return UserModel(
        preferences=load_category("preferences"),
        projects=load_category("projects"),
        people=load_category("people"),
        devices=load_category("devices"),
        routines=load_category("routines"),
        privacy_preferences=load_category("privacy_preferences"),
        restrictions=load_category("restrictions"),
    )


def save_user_model(model: UserModel) -> None:
    """Save the user model to disk."""
    path = _user_model_path()
    data = {
        "preferences": [_serialize_fact(f) for f in model.preferences],
        "projects": [_serialize_fact(f) for f in model.projects],
        "people": [_serialize_fact(f) for f in model.people],
        "devices": [_serialize_fact(f) for f in model.devices],
        "routines": [_serialize_fact(f) for f in model.routines],
        "privacy_preferences": [_serialize_fact(f) for f in model.privacy_preferences],
        "restrictions": [_serialize_fact(f) for f in model.restrictions],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def add_fact(category: str, fact: str, source: str = "observed_behavior", confidence: float = 0.5) -> UserFact:
    """Add a fact to the user model."""
    model = load_user_model()
    fact_id = f"fact_{int(time.time()*1000)}_{os.urandom(4).hex()}"
    new_fact = UserFact(
        fact_id=fact_id,
        fact=fact,
        source=source,
        confidence=confidence,
        category=category,
    )

    target = getattr(model, category, None)
    if target is None:
        raise ValueError(f"Unknown category: {category}")

    target.append(new_fact)
    save_user_model(model)
    return new_fact


def update_fact(fact_id: str, updates: dict[str, Any]) -> UserFact | None:
    """Update a fact by ID."""
    model = load_user_model()
    for category_name in ["preferences", "projects", "people", "devices", "routines", "privacy_preferences", "restrictions"]:
        facts = getattr(model, category_name)
        for i, f in enumerate(facts):
            if f.fact_id == fact_id:
                current = _serialize_fact(f)
                current.update(updates)
                current["fact_id"] = fact_id  # preserve ID
                updated = _deserialize_fact(current)
                facts[i] = updated
                save_user_model(model)
                return updated
    return None


def delete_fact(fact_id: str) -> bool:
    """Delete a fact by ID."""
    model = load_user_model()
    for category_name in ["preferences", "projects", "people", "devices", "routines", "privacy_preferences", "restrictions"]:
        facts = getattr(model, category_name)
        for i, f in enumerate(facts):
            if f.fact_id == fact_id:
                facts.pop(i)
                save_user_model(model)
                return True
    return False


def confirm_fact(fact_id: str) -> UserFact | None:
    """Confirm a fact, bumping its confidence."""
    return update_fact(fact_id, {
        "confidence": 1.0,
        "source": "explicit_user_instruction",
        "last_confirmed_at": time.time(),
    })


def get_relevant_facts(query: str = "", *, min_confidence: float = 0.5) -> list[UserFact]:
    """Get facts relevant to a query, filtered by minimum confidence."""
    model = load_user_model()
    all_facts: list[UserFact] = []
    for cat in [model.preferences, model.projects, model.people, model.devices, model.routines, model.privacy_preferences, model.restrictions]:
        all_facts.extend(cat)

    # Filter by confidence
    all_facts = [f for f in all_facts if f.confidence >= min_confidence]

    if not query:
        return all_facts

    # Simple keyword match
    query_lower = query.lower()
    scored = []
    for f in all_facts:
        score = 0
        if query_lower in f.fact.lower():
            score = 1.0
        elif any(word in f.fact.lower() for word in query_lower.split()):
            score = 0.5
        if score > 0:
            scored.append((score, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored]


def ensure_user_model_exists() -> UserModel:
    """Ensure the user model file exists, creating empty defaults if needed."""
    path = _user_model_path()
    if not path.exists():
        save_user_model(UserModel())
        return UserModel()
    return load_user_model()
