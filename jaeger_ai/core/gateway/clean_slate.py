"""Clean-slate pruning of the gateway session store.

Waking to an OS 1 welcome while the UI still shows last week's
conversations breaks the illusion the sequence exists to create. This
clears that history — but it is deliberately NOT part of
``jaeger onboarding reset``.

Why opt-in. §23 of the OS 1 spec draws a hard line: resetting first boot
must not erase the operator's broader data, and a full identity reset is a
separate, more consequential operation. Session transcripts are the
operator's record of real work; a flag that quietly deletes 65
conversations because someone wanted to re-see a greeting is the kind of
thing that is only noticed afterwards. So the welcome reset stays narrow,
and this lives behind ``--clean-slate``.

Two safeguards that are not optional:

* **Archive before pruning.** The whole database is copied aside first. If
  the operator wanted the history after all, it is one ``cp`` away.
* **Refuse while the daemon holds the lease.** The store records an owning
  pid. Deleting rows underneath a live gateway races its in-flight writes
  and can leave the WAL inconsistent; better to refuse and say so.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: Tables holding conversation history. Deliberately explicit rather than
#: "every table": ``schema_meta`` and ``event_retention`` are store
#: configuration, and wiping those would corrupt the database rather than
#: empty it.
HISTORY_TABLES = (
    "messages",
    "events",
    "client_requests",
    "background_deliveries",
    "handoffs",
    "approvals",
    "sessions",
)


@dataclass
class PruneResult:
    archived_to: Path | None
    removed: dict[str, int]
    refused: str | None = None

    @property
    def ok(self) -> bool:
        return self.refused is None

    @property
    def total_removed(self) -> int:
        return sum(self.removed.values())


def live_owner_pid(db_path: Path) -> int | None:
    """The pid holding the store's lease, if one is alive.

    ``None`` means no live owner — safe to prune. The gateway takes this
    lease on startup precisely so two processes cannot own the store.
    """
    if not db_path.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = con.execute(
            "select owner_pid from process_lease order by rowid desc limit 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row or not row[0]:
        return None

    pid = int(row[0])
    try:
        import os

        os.kill(pid, 0)          # signal 0 = liveness probe, no effect
    except (OSError, ProcessLookupError):
        return None              # stale lease from a crashed daemon
    return pid


def archive_store(db_path: Path, archive_root: Path | None = None) -> Path | None:
    """Copy the database aside. Returns the archive path, or None."""
    if not db_path.is_file():
        return None
    root = archive_root or (db_path.parent / "archive")
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = root / f"gateway_sessions-{stamp}.sqlite3"
    shutil.copy2(db_path, target)
    # WAL/SHM carry committed-but-uncheckpointed rows; copying the main
    # file alone can lose the most recent conversations, which are exactly
    # the ones someone would miss.
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if side.is_file():
            shutil.copy2(side, target.with_name(target.name + suffix))
    return target


def prune_history(
    db_path: Path,
    *,
    archive: bool = True,
    force: bool = False,
) -> PruneResult:
    """Empty the conversation tables. Archives first unless told not to.

    Refuses while a live daemon owns the store unless ``force``. The refusal
    is the useful behaviour: the fix is to stop the gateway, not to write
    underneath it.
    """
    if not db_path.is_file():
        return PruneResult(archived_to=None, removed={})

    owner = live_owner_pid(db_path)
    if owner is not None and not force:
        return PruneResult(
            archived_to=None, removed={},
            refused=(
                f"the gateway daemon (pid {owner}) owns this store. "
                "Stop it first — pruning underneath a live writer can leave "
                "the WAL inconsistent."
            ),
        )

    archived = archive_store(db_path) if archive else None

    removed: dict[str, int] = {}
    con = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        for table in HISTORY_TABLES:
            try:
                before = con.execute(f'select count(*) from "{table}"').fetchone()[0]
            except sqlite3.Error:
                continue        # table absent in this schema version
            if before:
                con.execute(f'delete from "{table}"')
                removed[table] = before
        con.commit()
        # Reclaim the pages so the file does not stay at its old size —
        # a 256K "empty" database invites the reasonable suspicion that
        # nothing was actually cleared.
        con.execute("VACUUM")
    finally:
        con.close()

    return PruneResult(archived_to=archived, removed=removed)


__all__ = [
    "HISTORY_TABLES",
    "PruneResult",
    "archive_store",
    "live_owner_pid",
    "prune_history",
]
