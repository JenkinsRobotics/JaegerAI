"""v1.1.0 → v1.2.0 — SQLite memory backend.

Brings a 0.2.0-pre instance's on-disk memory layout into the new
SQLite-backed shape (Group 9, DB-1..DB-7):

- ``facts.json``       → SQL ``facts``        table
- ``episodic.jsonl``   → SQL ``episodic``     table
- ``schedules.jsonl``  → SQL ``schedules``    table
- ``logs/audit.log``   → SQL ``audit_log``    table (mirror; JSONL stays)

The heavy lifting is already done by the lazy importers in
``core/memory/memory.py`` — each is gated on "SQL empty AND legacy
file present", so calling ``mem.bind(layout)`` here triggers all four
imports in one pass. What this migration adds on top is:

1. Hard idempotence: re-running is a no-op (the lazy importers
   already short-circuit).
2. Verification: every legacy file that contributed rows is renamed
   to ``<name>.legacy`` so the user can verify the migration before
   manual cleanup. We never delete data — the JSONL files stay on
   disk, just out of the active-write path.
3. Audit-log handling: the JSONL stays canonical. We do NOT rename
   ``logs/audit.log`` — the file is the tamper-evident forensic
   record. The SQL mirror is a queryable convenience; both stores
   stay in sync going forward.

The runner then bumps ``manifest.core_version`` from ``"1.1.0"`` to
``"1.2.0"`` automatically.
"""

from __future__ import annotations

from pathlib import Path

from jaeger_os.core.instance.instance import InstanceLayout


_LEGACY_FILES = (
    "facts.json",
    "episodic.jsonl",
    "schedules.jsonl",
)


def migrate(layout: InstanceLayout) -> None:
    """Apply the v1.1.0 → v1.2.0 changes to ``layout``.

    Idempotent — re-running is harmless (lazy importers short-circuit
    on populated tables; the ``.legacy`` rename is no-op when the
    source is already renamed).
    """
    # Step 1: bind memory at this layout. That triggers the lazy
    # imports for facts/episodic/schedules/audit_log. They're each
    # gated on "SQL empty AND legacy file present" so a re-run is a
    # silent no-op.
    from jaeger_os.core.memory import memory as mem
    from jaeger_os.core.memory import sqlite_store

    mem.bind(layout)

    # Step 2: rename JSON/JSONL stores to ``<name>.legacy`` so future
    # boots only see the SQL. We rename AFTER bind so that even if the
    # rename fails the data has already been imported.
    #
    # Only rename when SQL actually has rows (verifies the import
    # worked). Empty source files are left alone — nothing to verify.
    mem_dir: Path = layout.memory_dir
    conn = sqlite_store.connection()

    if conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] > 0:
        _rename_to_legacy(mem_dir / "facts.json")

    if conn.execute("SELECT COUNT(*) FROM episodic").fetchone()[0] > 0:
        _rename_to_legacy(mem_dir / "episodic.jsonl")
        # Embeddings cache too — replaced by ``episodic_embeddings``.
        _rename_to_legacy(mem_dir / "episodic.embeddings.npz")

    if conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0] > 0:
        _rename_to_legacy(mem_dir / "schedules.jsonl")

    # NOTE: audit.log stays in place. The on-disk JSONL is the
    # tamper-evident forensic record; SQL is a queryable mirror.
    # Both writers fire together in ``core/tools/_common.py:_audit``.


def _rename_to_legacy(p: Path) -> None:
    """Rename ``p`` to ``p.with_suffix(p.suffix + '.legacy')``. No-ops
    when the source doesn't exist or the target already does — both
    states are valid re-run scenarios."""
    if not p.exists():
        return
    target = p.with_name(p.name + ".legacy")
    if target.exists():
        # Previous run already renamed; nothing to do. We don't
        # overwrite to avoid clobbering a partial backup.
        return
    try:
        p.rename(target)
    except OSError:
        # Best-effort — leave the source in place. The data is
        # already in SQL; the user can rename manually later.
        pass
