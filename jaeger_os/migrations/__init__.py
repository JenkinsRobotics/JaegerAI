"""Per-release migration scripts (currently empty — framework is at v1.0.0).

The runner lives one level up at `core/migrations.py`. THIS directory
holds the actual versioned migration scripts. Empty today because the
framework just shipped its first version — no schema changes to migrate
between yet.

When a future core release ships a schema change (e.g. v1.0.0 → v1.1.0
adds a new required field to identity.yaml), drop a module here named:

    v<FROM>_to_v<TO>.py        e.g. v1_0_0_to_v1_1_0.py

with this shape:

    def migrate(layout):
        # `layout` is an InstanceLayout — has all the instance dir paths.
        # Open the affected files, rewrite them, write them back.
        # Be IDEMPOTENT — running again on an already-migrated instance
        # should be a no-op (check current shape first, return early).
        ...

The runner discovers these on startup, sorts by (FROM → TO) edge, and
applies them in order until the instance's manifest.json matches the
installed CORE_VERSION. On any failure it refuses to start — a partial
migration is worse than a clear refusal.

See `core/migrations.py` for the runner code + version-mismatch behavior.
"""
