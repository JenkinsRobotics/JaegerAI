"""Persona discovery + loading — wizard-time only.

A **persona** is a YAML template the setup wizard can use to prefill
the identity questions (name / role / personality / voice) and the
initial ``soul.md`` body.  See
[jaeger_os/personas/README.md](../../personas/README.md) for the file
format.

This module is **not** imported by the runtime prompt assembler.  It
only runs during ``./run.sh setup``.  After the wizard finishes, the
instance directory contains a plain ``identity.yaml`` + ``soul.md``;
nothing on the agent's hot path looks up persona IDs or reads from
``jaeger_os/personas/`` again.  The framework is therefore safe to
ship without committing to a runtime persona system (full character
levels, skill bundles, tool gates etc. land on the Lilith-AI line —
see ``personas/README.md`` for what's deferred).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# Persona ids must match this slug regex — kebab- or snake-case ASCII.
# Used to gate ``load_persona`` against path-traversal: a caller passing
# ``"../etc/passwd"`` would slip past a bare ``personas / f"{id}.yaml"``
# join.  Same shape as v3 manifest IDs.
_PERSONA_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


# Built-in persona directory — ships with the package.  Operators
# can drop additional YAML files here; per-instance overrides live
# on the Lilith line and aren't part of v1.
_PERSONAS_DIR = Path(__file__).resolve().parent.parent.parent / "personas"

# The only schema string the v1 loader accepts.  Bumped if/when the
# format gains breaking fields (character levels etc. will likely
# bump this to ``persona/v2``).
_SCHEMA_V1 = "persona/v1"


@dataclass
class PersonaIdentity:
    """The identity prefills a persona offers the wizard."""

    display_name: str
    role: str
    personality: str
    voice_tone: str = "neutral"
    voice_id: str | None = None


@dataclass
class Persona:
    """A loaded persona ready to hand to the wizard.

    ``soul_md`` is the markdown body the wizard will write verbatim
    to ``soul.md`` if the operator accepts the prefill.  ``None``
    means "don't pre-seed soul.md" (the operator can still write
    one later via ``update_soul``).
    """

    id: str
    name: str
    description: str
    identity: PersonaIdentity
    soul_md: str | None = None
    source_path: Path | None = field(default=None, repr=False)


class PersonaError(Exception):
    """Raised when a persona file is malformed."""


# ─── public API ────────────────────────────────────────────────────────

def personas_dir() -> Path:
    """Return the built-in persona directory.  Public so the wizard
    can mention the path in its error messages."""
    return _PERSONAS_DIR


def list_personas() -> list[Persona]:
    """Discover and load every valid persona under ``personas/``.

    Malformed files are skipped with a printed warning rather than
    raising — a broken add-on persona should never block setup.
    Result is sorted by ``id`` for stable wizard ordering.
    """
    found: list[Persona] = []
    if not _PERSONAS_DIR.exists():
        return found
    for path in sorted(_PERSONAS_DIR.glob("*.yaml")):
        try:
            found.append(_load_from_path(path))
        except PersonaError as exc:
            # Don't crash the wizard over a bad add-on file — surface
            # it and move on.  The built-in personas ship validated,
            # so this only fires on operator-added files.
            print(f"  [persona] skipping {path.name}: {exc}")
    found.sort(key=lambda p: p.id)
    return found


def load_persona(persona_id: str) -> Persona:
    """Load one persona by ID.  Raises ``PersonaError`` if the file
    doesn't exist, doesn't parse, doesn't pass schema checks, or if
    ``persona_id`` would resolve outside the personas directory
    (slash, ``..``, absolute path, etc.).
    """
    if not isinstance(persona_id, str) or not _PERSONA_ID_RE.match(persona_id):
        raise PersonaError(
            f"invalid persona id {persona_id!r}; expected "
            f"{_PERSONA_ID_RE.pattern}"
        )
    path = (_PERSONAS_DIR / f"{persona_id}.yaml").resolve()
    try:
        path.relative_to(_PERSONAS_DIR.resolve())
    except ValueError as exc:
        raise PersonaError(
            f"persona {persona_id!r} resolves outside {_PERSONAS_DIR}"
        ) from exc
    if not path.exists():
        raise PersonaError(
            f"persona {persona_id!r} not found in {_PERSONAS_DIR}"
        )
    return _load_from_path(path)


# ─── internals ─────────────────────────────────────────────────────────

def _load_from_path(path: Path) -> Persona:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PersonaError(f"couldn't read {path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PersonaError(f"{path.name}: top level must be a mapping")

    schema = raw.get("schema")
    if schema != _SCHEMA_V1:
        raise PersonaError(
            f"{path.name}: unsupported schema {schema!r} "
            f"(expected {_SCHEMA_V1!r})"
        )

    persona_id = _require_str(raw, "id", path)
    if persona_id != path.stem:
        raise PersonaError(
            f"{path.name}: id {persona_id!r} doesn't match filename"
        )

    identity_raw = raw.get("identity")
    if not isinstance(identity_raw, dict):
        raise PersonaError(f"{path.name}: missing 'identity' mapping")

    identity = PersonaIdentity(
        display_name=_require_str(identity_raw, "display_name", path,
                                  field_prefix="identity"),
        role=_require_str(identity_raw, "role", path,
                          field_prefix="identity"),
        personality=_require_str(identity_raw, "personality", path,
                                 field_prefix="identity"),
        voice_tone=_optional_str(identity_raw, "voice_tone",
                                 default="neutral"),
        voice_id=_optional_str(identity_raw, "voice_id"),
    )

    soul_md_raw = raw.get("soul_md")
    if soul_md_raw is not None and not isinstance(soul_md_raw, str):
        raise PersonaError(
            f"{path.name}: 'soul_md' must be a string (got {type(soul_md_raw).__name__})"
        )
    soul_md = soul_md_raw.strip() if soul_md_raw else None

    return Persona(
        id=persona_id,
        name=_require_str(raw, "name", path),
        description=_require_str(raw, "description", path),
        identity=identity,
        soul_md=soul_md or None,
        source_path=path,
    )


def _require_str(
    src: dict[str, Any],
    key: str,
    path: Path,
    *,
    field_prefix: str = "",
) -> str:
    full = f"{field_prefix}.{key}" if field_prefix else key
    value = src.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PersonaError(f"{path.name}: missing/empty {full!r}")
    return value.strip()


def _optional_str(
    src: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
) -> str | None:
    value = src.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        return default
    stripped = value.strip()
    return stripped or default
