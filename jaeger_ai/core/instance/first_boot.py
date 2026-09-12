"""OS 1 first boot — the durable state behind the two-question welcome.

First boot is the moment a person meets their SI for the first time. It asks
exactly two questions, one turn each, then hands off to the initialized
persona. That sequence is a product invariant, and the only thing that makes
it survivable is this file: a small, durable record of where the person got
to, so a crash, a reload, a double-click or a bridge reconnect never replays
a question they already answered — and never replays the welcome at all for
someone who finished it months ago.

State machine (one direction only, never backwards without an explicit
reset):

    NOT_STARTED ──► AWAITING_VOICE ──► AWAITING_Q2 ──► INITIALIZING_PERSONA ──► COMPLETED

Storage is ``<instance>/first_boot.yaml`` — the same shape as the persona
drift file and the person index: one small hand-editable YAML under the
instance root, no schema migration, read defensively because a human may
have opened it.

Two rules this module exists to enforce:

* **Idempotency.** Every transition is a no-op when it has already
  happened. Double clicks, duplicate HTTP posts, SSE reconnects and process
  restarts cannot create a second persona, a second name, or a second
  welcome. The transition functions return the state rather than raising,
  so a caller that fires twice gets the same answer twice.

* **Never replay for an established identity.** An instance that predates
  this feature has no ``first_boot.yaml``, which is indistinguishable from
  a brand-new one by file existence alone. :func:`classify_existing` reads
  durable evidence — an identity the operator already configured, memory,
  a persona — and marks those COMPLETED instead of marching a long-time
  user back through the welcome. When the evidence is ambiguous it refuses
  to guess and reports UNKNOWN, and the caller fails conservatively.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

STATE_FILENAME = "first_boot.yaml"

#: Bumped only when the shape below changes incompatibly. Readers tolerate
#: unknown keys, so additive fields do NOT need a bump.
SCHEMA_VERSION = 1


class FirstBootStatus(str, Enum):
    """Where this identity is in the welcome sequence."""

    NOT_STARTED = "NOT_STARTED"
    AWAITING_VOICE = "AWAITING_VOICE"
    AWAITING_Q2 = "AWAITING_Q2"
    INITIALIZING_PERSONA = "INITIALIZING_PERSONA"
    COMPLETED = "COMPLETED"


#: Forward order. Used to reject backwards transitions.
_ORDER: tuple[FirstBootStatus, ...] = (
    FirstBootStatus.NOT_STARTED,
    FirstBootStatus.AWAITING_VOICE,
    FirstBootStatus.AWAITING_Q2,
    FirstBootStatus.INITIALIZING_PERSONA,
    FirstBootStatus.COMPLETED,
)

#: The voice experience the person picked. Deliberately NOT a vendor voice
#: id — ``am_michael`` belongs to one TTS engine, and the preference has to
#: outlive whichever engine is installed. The capability router maps this
#: onto Apple / local / OpenAI / future providers at speak time.
VOICE_PROFILES = ("male", "female")


# ── paths ────────────────────────────────────────────────────────────


def instance_dir(instance_root: Path | Any) -> Path:
    """The instance directory, from either a path or an ``InstanceLayout``.

    The ``Path`` check comes first on purpose, and every caller must go
    through here rather than reaching for ``.root`` directly: ``Path``
    itself has a ``root`` attribute (``"/"`` for an absolute path), so a
    bare ``getattr(x, "root", x)`` silently resolves a perfectly good
    instance path to the filesystem root — where nothing exists, and an
    established identity reads as brand new.
    """
    root = instance_root
    if not isinstance(root, (str, Path)):
        root = getattr(root, "root", root)
    return Path(root)


def state_path(instance_root: Path | Any) -> Path:
    """``<instance>/first_boot.yaml``."""
    return instance_dir(instance_root) / STATE_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── read / write ─────────────────────────────────────────────────────


def _read(instance_root: Path | Any) -> dict[str, Any]:
    """The whole document, or ``{}``. Never raises.

    A corrupt or unreadable state file means "we don't know where they
    got to", not a dead agent. The caller treats ``{}`` as NOT_STARTED,
    which is the safe direction for a file that only ever appears on a
    machine that has begun first boot.
    """
    try:
        path = state_path(instance_root)
        if not path.is_file():
            return {}
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — runtime state must never break boot
        return {}
    return doc if isinstance(doc, dict) else {}


def _write(instance_root: Path | Any, doc: dict[str, Any]) -> None:
    """Atomically replace the state file.

    Written to a temp file in the same directory and ``os.replace``d, so a
    crash mid-write leaves the previous state intact rather than a
    half-truncated file that would read as ``{}`` and replay the welcome.
    """
    path = state_path(instance_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["schema_version"] = SCHEMA_VERSION
    payload = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".first_boot.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with __import__("contextlib").suppress(OSError):
            os.unlink(tmp)
        raise


# ── queries ──────────────────────────────────────────────────────────


def status(instance_root: Path | Any) -> FirstBootStatus:
    """Where this identity is. Unknown/corrupt values read as NOT_STARTED."""
    raw = str(_read(instance_root).get("status") or "")
    try:
        return FirstBootStatus(raw)
    except ValueError:
        return FirstBootStatus.NOT_STARTED


def is_complete(instance_root: Path | Any) -> bool:
    """True when the welcome must never be shown again."""
    return status(instance_root) is FirstBootStatus.COMPLETED


def snapshot(instance_root: Path | Any) -> dict[str, Any]:
    """The full record, for diagnostics and the bridge's status query."""
    doc = _read(instance_root)
    doc.setdefault("status", FirstBootStatus.NOT_STARTED.value)
    doc.setdefault("schema_version", SCHEMA_VERSION)
    return doc


def voice_profile(instance_root: Path | Any) -> str | None:
    """The chosen voice experience (``male``/``female``), or ``None``."""
    value = _read(instance_root).get("voice_profile")
    return value if value in VOICE_PROFILES else None


def persona_name(instance_root: Path | Any) -> str | None:
    """The name the SI chose for itself, if it has chosen one."""
    value = _read(instance_root).get("persona_name")
    return str(value) if value else None


# ── transitions (all idempotent) ─────────────────────────────────────


def _advance(doc: dict[str, Any], target: FirstBootStatus) -> bool:
    """True when ``target`` is forward of the current status.

    Backwards moves are ignored rather than raising: a duplicate request
    that arrives late (a retried POST, an SSE reconnect replaying a frame)
    must not drag a finished identity back into the welcome.
    """
    try:
        current = FirstBootStatus(str(doc.get("status") or FirstBootStatus.NOT_STARTED.value))
    except ValueError:
        current = FirstBootStatus.NOT_STARTED
    return _ORDER.index(target) > _ORDER.index(current)


def begin(instance_root: Path | Any) -> FirstBootStatus:
    """Start first boot. Safe to call on every boot.

    Returns the resulting status — already-started identities keep theirs,
    which is what makes "show the welcome if we're at AWAITING_VOICE" a
    correct check on a crashed-and-restarted process.
    """
    doc = _read(instance_root)
    if _advance(doc, FirstBootStatus.AWAITING_VOICE):
        doc["status"] = FirstBootStatus.AWAITING_VOICE.value
        doc.setdefault("started_at", _now())
        _write(instance_root, doc)
    return status(instance_root)


def record_voice(instance_root: Path | Any, profile: str) -> FirstBootStatus:
    """Persist the answer to question one and move to question two.

    Raises ``ValueError`` on an unknown profile — the caller normalises
    free text ("a female voice please") before reaching here, and an
    unrecognised value must not silently advance the sequence.
    """
    normalised = str(profile or "").strip().lower()
    if normalised not in VOICE_PROFILES:
        raise ValueError(
            f"voice_profile must be one of {VOICE_PROFILES}, got {profile!r}"
        )
    doc = _read(instance_root)
    # Record the answer even on a repeat call (the person may correct it
    # while still on the question), but only advance forward.
    doc["voice_profile"] = normalised
    doc.setdefault("voice_recorded_at", _now())
    if _advance(doc, FirstBootStatus.AWAITING_Q2):
        doc["status"] = FirstBootStatus.AWAITING_Q2.value
    _write(instance_root, doc)
    return status(instance_root)


def record_q2(
    instance_root: Path | Any,
    response: str,
    *,
    refused: bool = False,
) -> FirstBootStatus:
    """Persist the answer to question two and move to persona initialization.

    Any response is valid — a sentence, one word, a joke, a question back,
    or a refusal. ``refused=True`` records that the person declined without
    storing a non-answer as though it were disclosure. Nothing here
    interprets the content; calibration happens in the persona layer, and
    this module only guarantees the answer is durably recorded before the
    sequence advances.
    """
    doc = _read(instance_root)
    doc["q2_response"] = "" if refused else str(response or "")
    doc["q2_refused"] = bool(refused)
    doc.setdefault("q2_recorded_at", _now())
    if _advance(doc, FirstBootStatus.INITIALIZING_PERSONA):
        doc["status"] = FirstBootStatus.INITIALIZING_PERSONA.value
    _write(instance_root, doc)
    return status(instance_root)


def record_persona_name(
    instance_root: Path | Any,
    name: str,
    *,
    origin: str = "autonomous_initialization",
) -> str:
    """Record the name the SI chose. First write wins.

    The name is stable once chosen: a retried initialization must not
    rename an SI the person has already met. Returns the stored name,
    which may be the one from an earlier call.
    """
    doc = _read(instance_root)
    existing = doc.get("persona_name")
    if existing:
        return str(existing)
    doc["persona_name"] = str(name)
    doc["persona_name_origin"] = origin
    doc["persona_name_created_at"] = _now()
    _write(instance_root, doc)
    return str(name)


def complete(instance_root: Path | Any) -> FirstBootStatus:
    """Mark first boot finished. The welcome is never shown again."""
    doc = _read(instance_root)
    if _advance(doc, FirstBootStatus.COMPLETED):
        doc["status"] = FirstBootStatus.COMPLETED.value
        doc.setdefault("completed_at", _now())
        _write(instance_root, doc)
    return status(instance_root)


def reset(instance_root: Path | Any) -> None:
    """Clear first-boot state ONLY. Deliberate, explicit, narrow.

    This is ``jaeger onboarding reset``. It removes the welcome record so
    the sequence runs again — and it touches nothing else. Memory, the
    Library, projects, credentials, provider settings and the character
    sheet all survive, because wiping those is a different and far more
    consequential operation that the operator has to ask for by name.
    """
    path = state_path(instance_root)
    with __import__("contextlib").suppress(OSError):
        path.unlink()


# ── migration for identities that predate this feature ───────────────

#: Returned when existing state cannot be classified safely.
UNKNOWN = "UNKNOWN"


def classify_existing(layout: Any) -> str:
    """Decide whether an instance with no state file is new or established.

    The hazard this exists to prevent: shipping first boot would otherwise
    send every current operator back through the welcome, because "no
    ``first_boot.yaml``" looks identical for a fresh install and a
    two-year-old identity.

    Evidence that an identity predates the feature — any one is enough,
    because each takes deliberate setup or accumulated use that a brand-new
    instance cannot have:

    * a configured ``identity.yaml`` (the operator named and described it)
    * a manifest (the instance was created and versioned)
    * memory on disk (it has been used)

    Returns ``COMPLETED`` for an established identity, ``NOT_STARTED`` for
    one with no trace of prior use, and ``UNKNOWN`` when the instance root
    cannot be inspected at all — in which case the caller must fail
    conservatively rather than reset somebody's SI.
    """
    try:
        root = instance_dir(layout)
        if not root.is_dir():
            return FirstBootStatus.NOT_STARTED.value
    except Exception:  # noqa: BLE001 — an uninspectable root is not a new user
        return UNKNOWN

    try:
        if (root / "identity.yaml").is_file():
            return FirstBootStatus.COMPLETED.value
        if (root / "manifest.json").is_file():
            return FirstBootStatus.COMPLETED.value
        memory = root / "memory"
        if memory.is_dir() and any(
            p.name != ".gitkeep" for p in memory.iterdir()
        ):
            return FirstBootStatus.COMPLETED.value
    except Exception:  # noqa: BLE001 — ambiguous evidence must not reset anyone
        return UNKNOWN
    return FirstBootStatus.NOT_STARTED.value


def ensure_migrated(layout: Any) -> FirstBootStatus:
    """Classify an established identity once, so it skips the welcome.

    Idempotent: an instance that already has a state file is returned
    unchanged. An identity classified UNKNOWN is marked COMPLETED — the
    conservative direction, because wrongly skipping the welcome is a
    missing greeting, while wrongly replaying it looks to a long-time user
    like their SI forgot them.
    """
    if state_path(layout).is_file():
        return status(layout)

    verdict = classify_existing(layout)
    if verdict == FirstBootStatus.NOT_STARTED.value:
        return FirstBootStatus.NOT_STARTED

    doc: dict[str, Any] = {
        "status": FirstBootStatus.COMPLETED.value,
        "completed_at": _now(),
        "migrated": True,
        "migration_reason": (
            "predates_onboarding" if verdict == FirstBootStatus.COMPLETED.value
            else "unclassifiable_failed_safe"
        ),
    }
    _write(layout, doc)
    return FirstBootStatus.COMPLETED


__all__ = [
    "SCHEMA_VERSION",
    "STATE_FILENAME",
    "UNKNOWN",
    "VOICE_PROFILES",
    "FirstBootStatus",
    "begin",
    "classify_existing",
    "complete",
    "ensure_migrated",
    "is_complete",
    "persona_name",
    "record_persona_name",
    "record_q2",
    "record_voice",
    "reset",
    "snapshot",
    "state_path",
    "status",
    "voice_profile",
]
