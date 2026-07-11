# migrations/ — per-release schema migrations

> **Modification tier: C — Framework core.** Drop versioned
> migration scripts here as needed for future releases.  Test on
> a real instance before shipping.  Full policy:
> [`/dev/docs/core/SELF_MODIFICATION_BOUNDARIES.md`](../../dev/docs/core/SELF_MODIFICATION_BOUNDARIES.md).

## Status

**Currently empty** (other than `__init__.py`).  The 0.5.0
codebase reset the migration chain — pre-1.0 has no operators in
the wild, so the v1.0.0 → v1.1.0 → v1.2.0 chain (an exercise for
nonexistent users) was deleted along with the `legacy_migrations.py`
pre-resolver shim.  The runner ([`../core/instance/migrations.py`](
../core/instance/migrations.py)) is alive and will discover any
new modules added here on boot.

## Naming convention

Use the framework version this migration ships WITH:

    v<FROM>_to_<TO>.py    e.g.  v0_5_0_to_v0_6_0.py

`FROM` and `TO` use underscores in place of dots
(`v0_5_0_to_v0_6_0` ↔ "0.5.0 → 0.6.0").  The runner discovers
these, sorts them, and applies them in order until the instance's
`manifest.json:schema_version` matches the framework's
`SCHEMA_VERSION` constant (in `core/instance/schemas.py`).

## When to add a migration

When a framework release changes the shape of any file under
`<instance>/` in a way that needs translation:

- `<instance>/identity.yaml` adds/renames a required field
- `<instance>/config.yaml` schema bumps
- `<instance>/manifest.json` field renames
- Directory layout reorganisation
  (e.g. queued: `<instance>/progression/` + `<instance>/memories/`)
- File-format conversions (e.g. JSON → SQLite, plain text → msgspec)

When a release DOESN'T change schema, **don't ship a migration
file.**  The runner bumps the manifest's `schema_version` at boot
and continues.

## Migration script shape

```python
# v0_5_0_to_v0_6_0.py
def migrate(layout):
    """layout is an InstanceLayout — has all instance paths.
    Be idempotent — running again on a migrated instance should
    be a no-op (check current shape first, return early)."""

    # 1. Do the actual file moves / config edits.
    progression = layout.root / "progression"
    progression.mkdir(exist_ok=True)
    for fn in ("skill_tree.json", "personality.json"):
        src = layout.root / fn
        if src.exists():
            src.rename(progression / fn)

    # 2. Optionally return the TO version (helps the runner
    #    catch silent name-vs-version mismatches).
    return "0.6.0"
```

## What the runner does

1. Reads `<instance>/manifest.json:schema_version`
2. Compares to the framework's `SCHEMA_VERSION` constant
3. If different: discovers all `v*_to_*.py` modules, builds a
   chain `current → ... → SCHEMA_VERSION`, applies them in order
4. After each step: writes the new version to manifest.json so
   a crash mid-chain doesn't lose progress
5. If any step throws: refuses to start — a partial migration is
   worse than a clear refusal.

## Design principles

- **Forward-only.** No `v0_6_0_to_v0_5_0.py`.  Operators don't
  downgrade.
- **One step at a time.**  Each script crosses ONE version edge.
- **Idempotent where possible.**  `mkdir(exist_ok=True)`,
  check before delete, never assume a clean slate.
- **Crash-safe.**  Manifest version doesn't advance until the
  step succeeds.
- **Touches user data, never framework code.**  Migrations are
  about translating `<instance>/`, never modifying `jaeger_os/`.

## Pre-1.0 hygiene

Per the operator's `feedback-no-back-compat-pre-1.0` memory:
drop legacy code paths, dual-field-name reads, and "in case
someone has the old format" branches.  No operators in the wild
today, so defensive code for nonexistent operators is dead
weight.  When 1.0.0 ships, the migrations directory starts
accumulating in earnest.

See [`../core/instance/migrations.py`](../core/instance/migrations.py)
for the runner.
