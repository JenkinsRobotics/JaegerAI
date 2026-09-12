"""Per-release schema migration scripts (currently empty).

The 0.5.0 reset cleared the migration chain — pre-1.0 has no
operators in the wild, so the v1.0.0 → v1.1.0 → v1.2.0 chain
(an exercise for nonexistent users) was deleted along with the
``core/instance/legacy_migrations.py`` pre-resolver shim.  Per
the operator's ``feedback-no-back-compat-pre-1.0`` memory.

The runner lives at ``core/instance/migrations.py``.  THIS
directory holds versioned migration scripts.  Empty until a real
schema change ships.

When a future release ships a schema change, drop a module here
named for the framework version edge it crosses:

    v<FROM>_to_v<TO>.py        e.g. v0_5_0_to_v0_6_0.py

with this shape:

    def migrate(layout):
        # ``layout`` is an InstanceLayout — has all the instance
        # dir paths.  Open the affected files, rewrite them,
        # write them back.  Be IDEMPOTENT — running again on an
        # already-migrated instance should be a no-op.
        ...

The runner discovers these on startup, sorts by (FROM → TO) edge,
and applies them in order until the instance's manifest matches
the framework's ``SCHEMA_VERSION``.  On any failure it refuses to
start — a partial migration is worse than a clear refusal.

See ``core/instance/migrations.py`` for the runner.
See ``README.md`` for the full naming convention + design
principles.
"""
