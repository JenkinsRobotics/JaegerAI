"""Recoverable state-directory migration (historical F04/M1.3 task).

Moves one Jaeger-owned state directory to a new location as a phased state
machine::

    discover -> preflight -> lock -> backup -> stage -> verify -> activate -> complete

Every phase is recorded in a versioned manifest *before* the next begins, in
a work directory beside the destination (``<destination>.migration``, same
filesystem, so activation is one atomic ``rename``). Properties:

* **No source file is modified or deleted.** Retention is the operator's
  decision; nothing reads the source once the destination is active. (Reading
  a WAL-mode database lets SQLite create its standard ``-wal``/``-shm``
  sidecars beside it, as any reader does; database content is unchanged.)
* **SQLite is copied with the backup API**, which yields a consistent
  snapshot including WAL content — never a blind byte copy of a live
  ``.db``. Each copy passes ``PRAGMA integrity_check`` and per-table row
  counts must match the source.
* **Activation is atomic**: the verified staging directory is renamed onto
  the (absent) destination. A reader sees either no destination or a
  complete one, never a mixed generation.
* **Interrupted runs resume**: re-running after a crash at any phase either
  finishes activation (if the rename already happened), re-activates a
  still-verified staging copy, or discards only its own scratch and starts
  over. A completed migration is a no-op.
* **Conflicts are reported, never merged**: a non-empty destination that
  did not come from this migration stops the migration with a report.
* **Concurrent migrators are excluded** by an exclusive lock.

Credentials are copied as files (they are part of the state) but no file
content is ever written into the manifest — only relative paths, sizes and
SHA-256 digests.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

MANIFEST_VERSION = 1
PHASES = ("discover", "preflight", "lock", "backup", "stage", "verify", "activate", "complete")
_SQLITE_HEADER = b"SQLite format 3\x00"
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
#: How long a backup waits on a source database another process is writing.
SOURCE_BUSY_TIMEOUT_S = 10.0


class MigrationConflict(RuntimeError):
    """Source and destination both hold state; refusing to merge."""


class MigrationBusy(RuntimeError):
    """Another migrator holds the lock."""


class MigrationFailed(RuntimeError):
    """A phase failed; the manifest records where. Safe to re-run."""


@dataclass
class MigrationResult:
    status: str  # nothing_to_migrate | already_migrated | migrated
    destination: Path
    manifest_path: Path | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _checkpoint(phase: str) -> None:
    """Crash-injection seam for tests. Production: no-op."""


def work_dir_for(destination: Path) -> Path:
    return destination.with_name(destination.name + ".migration")


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(16) == _SQLITE_HEADER
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk(root: Path) -> Iterator[Path]:
    """Regular files under ``root``, relative, not following symlinks out."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path.relative_to(root)


def _db_facts(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sorted(tables)}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    return {"integrity": integrity, "tables": counts, "user_version": version}


def _copy_tree(source: Path, target: Path) -> dict[str, Any]:
    """Copy ``source`` into a fresh ``target``; SQLite via the backup API.

    Returns the inventory: ``files`` (rel -> sha256/size) and ``databases``
    (rel -> integrity/table counts), measured on the SOURCE snapshot.
    """
    target.mkdir(parents=True, exist_ok=False)
    inventory: dict[str, Any] = {"files": {}, "databases": {}}
    relatives = sorted(_walk(source))
    databases = {rel for rel in relatives if _is_sqlite(source / rel)}
    sidecars = {
        rel for rel in relatives
        for db in databases
        if str(rel) in {str(db) + suffix for suffix in _SQLITE_SIDECARS}
    }
    for rel in relatives:
        if rel in sidecars:
            continue  # folded into the database's backup snapshot
        src, dst = source / rel, target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel in databases:
            source_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=SOURCE_BUSY_TIMEOUT_S)
            target_conn = sqlite3.connect(dst)
            deadline = time.monotonic() + SOURCE_BUSY_TIMEOUT_S

            def bounded(status: int, remaining: int, total: int) -> None:
                # CPython's backup() retries a BUSY/LOCKED source forever;
                # a writer that never lets go must fail the phase instead.
                if time.monotonic() > deadline:
                    raise sqlite3.OperationalError(f"{rel} stayed locked for {SOURCE_BUSY_TIMEOUT_S}s")

            try:
                source_conn.backup(target_conn, pages=256, progress=bounded, sleep=0.05)
            finally:
                target_conn.close()
                source_conn.close()
            inventory["databases"][str(rel)] = _db_facts(dst)
        else:
            shutil.copy2(src, dst)
            inventory["files"][str(rel)] = {"sha256": _sha256(src), "size": src.stat().st_size}
    for rel in relatives:
        if (source / rel).stat().st_mode & 0o077 == 0:
            with contextlib.suppress(OSError):
                os.chmod(target / rel, 0o600)  # keep private files private
    return inventory


def _verify(copy: Path, inventory: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for rel, facts in inventory["files"].items():
        path = copy / rel
        if not path.is_file():
            problems.append(f"missing file {rel}")
        elif _sha256(path) != facts["sha256"]:
            problems.append(f"content mismatch {rel}")
    for rel, facts in inventory["databases"].items():
        path = copy / rel
        if not path.is_file():
            problems.append(f"missing database {rel}")
            continue
        actual = _db_facts(path)
        if actual["integrity"] != "ok":
            problems.append(f"integrity {rel}: {actual['integrity']}")
        if actual["tables"] != facts["tables"]:
            problems.append(f"row counts differ {rel}")
    return problems


def _space_needed(source: Path) -> int:
    return sum((source / rel).stat().st_size for rel in _walk(source))


class _Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        if path.is_file():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def write(self, **updates: Any) -> None:
        self.data.update(updates, updated_at=time.time())
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(self.data, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.path)
        _fsync_dir(self.path.parent)


def _fsync_dir(path: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextlib.contextmanager
def _exclusive(lock_path: Path) -> Iterator[None]:
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EACCES):
                raise MigrationBusy(f"another migration holds {lock_path}") from exc
            raise
        yield
    finally:
        os.close(fd)


def migrate_directory(source: Path, destination: Path, *, kind: str) -> MigrationResult:
    """Move the state at ``source`` to ``destination`` (see module docstring).

    Raises :class:`MigrationConflict`, :class:`MigrationBusy` or
    :class:`MigrationFailed`; each leaves the source intact and the run
    resumable.
    """
    source = source.expanduser()
    destination = destination.expanduser()
    work = work_dir_for(destination)
    manifest_path = work / "manifest.json"

    # discover
    _checkpoint("discover")
    manifest = _Manifest(manifest_path) if manifest_path.is_file() else None
    if manifest and manifest.data.get("phase") == "complete" and destination.exists():
        return MigrationResult("already_migrated", destination, manifest_path)
    if not source.exists() or source.is_symlink():
        if destination.exists():
            return MigrationResult("already_migrated", destination, manifest_path if manifest else None)
        return MigrationResult("nothing_to_migrate", destination)
    if destination.exists() and not manifest:
        if destination.is_dir() and not any(destination.iterdir()):
            destination.rmdir()  # an empty placeholder holds no state
        else:
            raise MigrationConflict(
                f"both {source} and {destination} hold state; refusing to merge. "
                "Choose one (move the other aside) and re-run."
            )

    work.mkdir(parents=True, exist_ok=True)
    with _exclusive(work / "lock"):
        manifest = _Manifest(manifest_path)
        staging = work / "staging"
        backup = work / "backup"
        phase = manifest.data.get("phase")

        # Resume an interrupted activation first: the rename is the commit point.
        if phase == "activate":
            if destination.exists() and not staging.exists():
                manifest.write(phase="complete", completed_at=time.time())
                return MigrationResult("migrated", destination, manifest_path, {"resumed": True})
            if staging.exists() and not destination.exists() and not _verify(staging, manifest.data["inventory"]):
                os.rename(staging, destination)
                _fsync_dir(destination.parent)
                manifest.write(phase="complete", completed_at=time.time())
                return MigrationResult("migrated", destination, manifest_path, {"resumed": True})
        if destination.exists():
            raise MigrationConflict(f"{destination} appeared during migration; refusing to merge")

        # Anything else unfinished: discard only our own scratch, start over.
        for scratch in (staging, backup):
            if scratch.exists():
                shutil.rmtree(scratch)
        manifest.data = {}
        run_id = uuid.uuid4().hex
        manifest.write(
            manifest_version=MANIFEST_VERSION, id=run_id, kind=kind,
            source=str(source), destination=str(destination),
            phase="preflight", started_at=time.time(),
            backup=str(backup), staging=str(staging),
        )

        # preflight
        _checkpoint("preflight")
        needed = _space_needed(source)
        free = shutil.disk_usage(work).free
        if free < 2 * needed + (16 << 20):
            manifest.write(phase="preflight", error="insufficient free space")
            raise MigrationFailed(f"need ~{2 * needed} bytes free at {work}, have {free}")
        manifest.write(phase="lock")
        _checkpoint("lock")

        try:
            # backup: a verified, retained snapshot of the source
            manifest.write(phase="backup")
            _checkpoint("backup")
            inventory = _copy_tree(source, backup)
            problems = _verify(backup, inventory)
            if problems:
                raise MigrationFailed(f"backup verification failed: {problems}")
            manifest.write(inventory=inventory)

            # stage: the generation that will become the destination
            manifest.write(phase="stage")
            _checkpoint("stage")
            _copy_tree(backup, staging)

            manifest.write(phase="verify")
            _checkpoint("verify")
            problems = _verify(staging, inventory)
            if problems:
                raise MigrationFailed(f"staging verification failed: {problems}")

            # activate: one atomic rename is the commit point
            manifest.write(phase="activate")
            _checkpoint("activate")
            os.rename(staging, destination)
            _fsync_dir(destination.parent)
            _checkpoint("activated")
            manifest.write(phase="complete", completed_at=time.time())
        except (MigrationFailed, MigrationConflict):
            raise
        except sqlite3.DatabaseError as exc:
            manifest.write(error=f"{type(exc).__name__}: {exc}")
            raise MigrationFailed(f"source database unreadable: {exc}") from exc
        except OSError as exc:
            manifest.write(error=f"{type(exc).__name__}: {exc}")
            raise MigrationFailed(str(exc)) from exc
    return MigrationResult("migrated", destination, manifest_path,
                           {"files": len(inventory["files"]), "databases": len(inventory["databases"])})


__all__ = [
    "MANIFEST_VERSION", "MigrationBusy", "MigrationConflict", "MigrationFailed",
    "MigrationResult", "PHASES", "migrate_directory", "work_dir_for",
]
