"""
ARES SI — Persistent identity configuration.

The SI identity is NOT a system prompt. It's structured data that gets
composed into different sections of the worker briefing depending on
what the worker needs to know.

Stored in ~/.ares/si/identity.json — human-readable, editable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _identity_path() -> Path:
    """Return the path to the identity config file."""
    ares_home = os.environ.get("ARES_HOME", os.path.expanduser("~/.ares"))
    si_dir = Path(ares_home) / "si"
    si_dir.mkdir(parents=True, exist_ok=True)
    return si_dir / "identity.json"


@dataclass
class SIIdentityConfig:
    """Full identity configuration for the Companion.

    This is what the SI IS — not what a worker is told to pretend to be.
    """
    name: str = "ARES"
    owner_name: str = ""
    mission: str = "Assist the owner accurately, protect their data, and be honest about uncertainty."
    principles: list[str] = field(default_factory=lambda: [
        "Be honest about what you know and don't know",
        "Protect the owner's private data",
        "Never share secrets with external services",
        "Explain your reasoning when asked",
        "Admit mistakes and correct them",
    ])
    loyalty: str = "user"
    communication_style: str = ""       # concise, detailed, casual, technical
    uncertainty_behavior: str = "ask"   # ask, flag, proceed
    privacy_commitment: str = "Private data stays local. Secrets never leave this device."
    disagreement_conditions: list[str] = field(default_factory=list)
    refusal_conditions: list[str] = field(default_factory=list)
    approval_conditions: list[str] = field(default_factory=lambda: [
        "shell_execute",
        "file_delete",
        "send_message",
    ])


_DEFAULTS = SIIdentityConfig()


def load_identity() -> SIIdentityConfig:
    """Load the identity from disk, or return defaults."""
    path = _identity_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return _DEFAULTS

    if not isinstance(data, dict):
        return _DEFAULTS

    return SIIdentityConfig(
        name=str(data.get("name", _DEFAULTS.name)),
        owner_name=str(data.get("owner_name", _DEFAULTS.owner_name)),
        mission=str(data.get("mission", _DEFAULTS.mission)),
        principles=list(data.get("principles", _DEFAULTS.principles)),
        loyalty=str(data.get("loyalty", _DEFAULTS.loyalty)),
        communication_style=str(data.get("communication_style", _DEFAULTS.communication_style)),
        uncertainty_behavior=str(data.get("uncertainty_behavior", _DEFAULTS.uncertainty_behavior)),
        privacy_commitment=str(data.get("privacy_commitment", _DEFAULTS.privacy_commitment)),
        disagreement_conditions=list(data.get("disagreement_conditions", _DEFAULTS.disagreement_conditions)),
        refusal_conditions=list(data.get("refusal_conditions", _DEFAULTS.refusal_conditions)),
        approval_conditions=list(data.get("approval_conditions", _DEFAULTS.approval_conditions)),
    )


def save_identity(config: SIIdentityConfig) -> None:
    """Save the identity to disk."""
    path = _identity_path()
    data = {
        "name": config.name,
        "owner_name": config.owner_name,
        "mission": config.mission,
        "principles": config.principles,
        "loyalty": config.loyalty,
        "communication_style": config.communication_style,
        "uncertainty_behavior": config.uncertainty_behavior,
        "privacy_commitment": config.privacy_commitment,
        "disagreement_conditions": config.disagreement_conditions,
        "refusal_conditions": config.refusal_conditions,
        "approval_conditions": config.approval_conditions,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def patch_identity(updates: dict[str, Any]) -> SIIdentityConfig:
    """Apply partial updates to the identity and save."""
    current = load_identity()
    for key, value in updates.items():
        if hasattr(current, key):
            setattr(current, key, value)
    save_identity(current)
    return current


def ensure_identity_exists() -> SIIdentityConfig:
    """Ensure the identity file exists, creating it with defaults if needed."""
    path = _identity_path()
    if not path.exists():
        save_identity(_DEFAULTS)
        return _DEFAULTS
    return load_identity()
