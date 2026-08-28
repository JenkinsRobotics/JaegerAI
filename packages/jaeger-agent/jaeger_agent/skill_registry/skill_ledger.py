"""Per-mutation skill audit ledger + single-edit rollback.

Ported from hermes-agent ``tools/skill_ledger.py``. hermes-agent is MIT
licensed:

    Copyright (c) 2025 Nous Research

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software.

Every skill mutation — regardless of actor — appends one JSONL entry to
``<instance>/skills/.curator_ledger.jsonl`` describing who changed what,
with before/after file manifests whose contents are stored content-addressed
(sha256-deduped) under ``<instance>/.curator_backups/blobs/``.

The donor's design decisions carry over unchanged, because they are the
reason the thing is worth having:

  - JSONL, not the state DB: a durable, human-greppable audit trail that
    survives DB resets and is trivially rsync/backup friendly.
  - The ledger covers ALL actors, tagged ``curator`` / ``agent`` / ``user``.
  - Per-file content-addressed blobs, not tarballs: a mutation typically
    touches one file, and identical content across entries dedupes to a
    single blob.
  - The ledger is TELEMETRY, NOT A GATE: a ledger failure must never block
    the mutation it describes. Every public write path is wrapped so
    exceptions are logged and swallowed. The one deliberate exception is
    :func:`rollback_entry`, which FAILS CLOSED when its own pre-rollback
    safety capture fails.

ADAPTATIONS for Jaeger:

  - ``get_hermes_home()`` → :func:`jaeger_agent.workspace.get_layout`. Paths
    are per-instance rather than per-user, so two Jaeger instances keep
    independent ledgers, matching how the rest of instance state is scoped.
  - The donor's ``skills.ledger`` config key has no Jaeger counterpart, so
    the gate is the ``JAEGER_SKILL_LEDGER`` env var, default ON.
  - The donor derives a ``curator`` actor from ``skill_provenance``'s
    background-review ContextVar. Jaeger has no such signal, so the explicit
    override is the only route to ``curator``; ``background/skill_review.py``
    and the Deep Think runner are the intended callers.

Why Jaeger wants this more than the donor did: Jaeger's Deep Think queue
writes skills autonomously (``background/deep_think.py``), so mutations
land without a human in the loop. Before this module there was a manifest
provenance field and a revision log, but no reversible record of the file
contents themselves.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ACTOR_CURATOR = "curator"
ACTOR_AGENT = "agent"
ACTOR_USER = "user"
_VALID_ACTORS = {ACTOR_CURATOR, ACTOR_AGENT, ACTOR_USER}

# Explicit actor override for call sites that know who they are acting for:
# the CLI sets "user", the skill-review sweep sets "curator".
_actor_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "jaeger_skill_ledger_actor", default=None
)


def set_ledger_actor(actor: str | None) -> contextvars.Token:
    """Bind an explicit actor for subsequent ledger records in this context.

    Returns a Token; callers must :func:`reset_ledger_actor` in a finally.
    """
    return _actor_override.set(actor)


def reset_ledger_actor(token: contextvars.Token) -> None:
    _actor_override.reset(token)


def derive_actor() -> str:
    """Best-effort actor derivation: explicit override, else ``agent``."""
    override = _actor_override.get()
    if override in _VALID_ACTORS:
        return override
    return ACTOR_AGENT


# ---------------------------------------------------------------------------
# Paths + config gate
# ---------------------------------------------------------------------------

def _root() -> Path:
    """The instance root. Raises if the workspace is unbound — callers in
    this module are all wrapped, so an unbound workspace degrades to a
    disabled ledger rather than an exception reaching a mutation site."""
    from jaeger_agent.workspace import get_layout

    return get_layout().root


def ledger_path() -> Path:
    from jaeger_agent.workspace import get_layout

    return get_layout().skills_dir / ".curator_ledger.jsonl"


def blobs_dir() -> Path:
    return _root() / ".curator_backups" / "blobs"


def ledger_enabled() -> bool:
    """Gate on ``JAEGER_SKILL_LEDGER`` (default ON).

    Also returns False when the workspace is unbound, so importing this
    module in a bare unit test can never raise from a mutation call site.
    """
    val = os.environ.get("JAEGER_SKILL_LEDGER", "").strip().lower()
    if val in ("0", "false", "no", "off"):
        return False
    try:
        _root()
    except Exception as e:  # pragma: no cover — unbound workspace
        logger.debug("skill_ledger: workspace unbound (%s); ledger inactive", e)
        return False
    return True


# ---------------------------------------------------------------------------
# Blob store (content-addressed, deduped)
# ---------------------------------------------------------------------------

def _store_blob(data: bytes) -> str:
    """Write *data* to the blob store keyed by its sha256. Dedupes: an
    existing blob with the same hash is left alone. Returns the hash."""
    digest = hashlib.sha256(data).hexdigest()
    dest = blobs_dir() / digest
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".tmp-{uuid.uuid4().hex[:8]}-{digest}")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    return digest


def read_blob(sha256: str) -> bytes | None:
    """Return blob content or None when missing/invalid."""
    if not sha256 or not all(c in "0123456789abcdef" for c in sha256):
        return None
    try:
        p = blobs_dir() / sha256
        return p.read_bytes() if p.exists() else None
    except OSError:
        return None


def snapshot_paths(root: Path | None) -> list[dict[str, str]]:
    """Capture ``{path, sha256}`` for every file under *root* (recursively),
    storing each file's content as a blob. Empty list when root is None or
    doesn't exist. Raises on I/O failure — callers decide whether that is
    fatal (rollback safety capture) or swallowed (telemetry hooks)."""
    if root is None:
        return []
    root = Path(root)
    if root.is_file():
        files = [root]
    elif root.is_dir():
        files = sorted(p for p in root.rglob("*") if p.is_file())
    else:
        return []
    out: list[dict[str, str]] = []
    for f in files:
        data = f.read_bytes()
        out.append({"path": str(f), "sha256": _store_blob(data)})
    return out


# ---------------------------------------------------------------------------
# Append + read
# ---------------------------------------------------------------------------

def append_entry(
    action: str,
    skill: str,
    before: list[dict[str, str]] | None = None,
    after: list[dict[str, str]] | None = None,
    actor: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> str | None:
    """Append one ledger entry. Returns the entry id, or None when the
    ledger is disabled or the write failed (never raises)."""
    if not ledger_enabled():
        return None
    try:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor if actor in _VALID_ACTORS else derive_actor(),
            "action": action,
            "skill": skill,
            "evidence": evidence or {},
            "before": before or [],
            "after": after or [],
        }
        path = ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry["id"]
    except Exception as e:
        logger.warning(
            "skill_ledger: failed to append entry (%s) — mutation unaffected", e)
        return None


def record_mutation(
    action: str,
    skill: str,
    before_root: Path | None = None,
    before: list[dict[str, str]] | None = None,
    after_root: Path | None = None,
    actor: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> str | None:
    """One-stop hook for mutation call sites: capture after-state from
    *after_root* (pre-captured *before* list, or capture from *before_root*)
    and append. NEVER raises and never blocks the mutation."""
    if not ledger_enabled():
        return None
    try:
        if before is None:
            before = snapshot_paths(before_root)
        after = snapshot_paths(after_root)
        return append_entry(
            action, skill, before=before, after=after, actor=actor,
            evidence=evidence,
        )
    except Exception as e:
        logger.warning(
            "skill_ledger: record_mutation failed (%s) — mutation unaffected", e)
        return None


def capture_before(root: Path | None) -> list[dict[str, str]] | None:
    """Best-effort pre-mutation capture. Returns None on failure or when the
    ledger is disabled (callers pass the result straight to
    :func:`record_mutation`)."""
    if not ledger_enabled():
        return None
    try:
        return snapshot_paths(root)
    except Exception as e:
        logger.warning(
            "skill_ledger: before-capture failed (%s) — mutation unaffected", e)
        return None


def list_entries(
    skill: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Read the ledger, newest first. Malformed lines are skipped."""
    try:
        path = ledger_path()
    except Exception:
        return []
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    if skill:
        rows = [r for r in rows if r.get("skill") == skill]
    rows.reverse()
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    return rows


def get_entry(entry_id: str) -> dict[str, Any] | None:
    if not entry_id:
        return None
    for row in list_entries():
        if row.get("id") == entry_id:
            return row
    return None


# ---------------------------------------------------------------------------
# Single-edit rollback
# ---------------------------------------------------------------------------

def _is_within(root: Path, path: Path) -> bool:
    """True when *path* sits under *root*. Handles ``..`` traversal."""
    try:
        root_r = Path(os.path.normpath(str(root)))
        path_r = Path(os.path.normpath(str(path)))
        return path_r == root_r or root_r in path_r.parents
    except Exception:
        return False


def _validate_entry_paths(entry: dict[str, Any]) -> str | None:
    """All paths in an entry must live under the instance root. Defense in
    depth — a hand-edited ledger must not become a write-anywhere primitive."""
    root = _root()
    for section in ("before", "after"):
        for item in entry.get(section) or []:
            p = Path(str(item.get("path", "")))
            if not _is_within(root, p):
                return f"entry references a path outside {root}: {p}"
    return None


def rollback_entry(entry_id: str) -> tuple[bool, str]:
    """Restore the before-state of the single mutation *entry_id*.

    Fail-closed semantics, carried over from the donor:
      1. Every needed before-blob must exist — verified BEFORE any change.
      2. A pre-rollback safety ledger entry capturing the CURRENT state of
         every touched path is appended first; if that capture fails, the
         rollback aborts and nothing is changed.
    """
    entry = get_entry(entry_id)
    if entry is None:
        return False, f"no ledger entry with id '{entry_id}'"

    try:
        path_err = _validate_entry_paths(entry)
    except Exception as e:
        return False, f"refusing rollback: could not resolve instance root ({e})"
    if path_err:
        return False, f"refusing rollback: {path_err}"

    before = entry.get("before") or []
    after = entry.get("after") or []

    # Pre-check every blob we need so we never fail mid-restore.
    for item in before:
        if read_blob(str(item.get("sha256", ""))) is None:
            return False, (
                f"missing blob {item.get('sha256')} for {item.get('path')}; "
                "rollback aborted, nothing was changed"
            )

    # Touched paths = union of before/after. Capture their CURRENT state as
    # the safety entry so the rollback itself is undoable. FAIL CLOSED.
    touched = {str(i["path"]) for i in before + after if i.get("path")}
    try:
        safety_before: list[dict[str, str]] = []
        for p in sorted(touched):
            fp = Path(p)
            if fp.is_file():
                safety_before.append(
                    {"path": p, "sha256": _store_blob(fp.read_bytes())})
        safety_id = append_entry(
            "pre-rollback",
            entry.get("skill", "?"),
            before=safety_before,
            after=safety_before,
            evidence={"rollback_target": entry_id},
        )
    except Exception as e:
        return False, (
            f"pre-rollback safety capture failed ({e}); rollback aborted and "
            "current skills were not changed"
        )
    if safety_id is None:
        return False, (
            "pre-rollback safety capture failed (ledger disabled or "
            "unwritable); rollback aborted and current skills were not changed"
        )

    # Restore: write every before-file, remove files the mutation created.
    before_paths = {str(i["path"]) for i in before}
    restored = 0
    removed = 0
    for item in before:
        fp = Path(str(item["path"]))
        data = read_blob(str(item["sha256"]))
        assert data is not None  # pre-checked above
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(data)
        restored += 1
    for item in after:
        p = str(item.get("path", ""))
        if p and p not in before_paths:
            fp = Path(p)
            try:
                if fp.is_file():
                    fp.unlink()
                    removed += 1
            except OSError as e:
                logger.warning(
                    "skill_ledger: could not remove %s during rollback: %s", p, e)

    append_entry(
        "rollback",
        entry.get("skill", "?"),
        before=safety_before,
        after=before,
        evidence={"rollback_target": entry_id, "restored": restored,
                  "removed": removed},
    )
    return True, (
        f"rolled back entry {entry_id} ({entry.get('action')} on "
        f"'{entry.get('skill')}'): {restored} file(s) restored, {removed} "
        f"removed. Safety entry {safety_id} captured the pre-rollback state."
    )


__all__ = [
    "ACTOR_AGENT", "ACTOR_CURATOR", "ACTOR_USER",
    "append_entry", "blobs_dir", "capture_before", "derive_actor",
    "get_entry", "ledger_enabled", "ledger_path", "list_entries",
    "read_blob", "record_mutation", "reset_ledger_actor", "rollback_entry",
    "set_ledger_actor", "snapshot_paths",
]
