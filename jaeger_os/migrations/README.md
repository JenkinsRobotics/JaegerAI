# migrations/ — per-release schema migrations

> **Modification tier: C — Framework core.** Drop versioned migration
> scripts here as needed for future releases. Test on a real instance
> before shipping. Full policy:
> [`/docs/SELF_MODIFICATION_BOUNDARIES.md`](../../../docs/SELF_MODIFICATION_BOUNDARIES.md).

## Status

**Currently empty** (other than the placeholder `__init__.py`). The
framework just shipped v1.0.0 — no schema changes to migrate between
yet. The runner ([`../core/migrations.py`](../core/migrations.py))
discovers any modules added here on boot and applies them in order.

## When to add a migration

When a core release changes the shape of:

- `<instance>/identity.yaml`
- `<instance>/config.yaml`
- `<instance>/manifest.json`
- `<instance>/memory/facts.json`
- any other persisted file the framework reads at boot

…you need a migration script so existing instances don't refuse to
start.

## Convention

```
src/jaeger_os/migrations/v<FROM>_to_v<TO>.py
```

e.g. `v1_0_0_to_v1_1_0.py`. Each module exposes:

```python
def migrate(layout: InstanceLayout) -> None:
    """Read affected files, rewrite, write back.

    Must be IDEMPOTENT — running on an already-migrated instance
    must be a no-op (check current shape first, return early).
    """
```

The runner sorts by (FROM → TO) edge and applies in order until the
instance's `manifest.json` matches the installed `CORE_VERSION`. Any
failure refuses to start — a partial migration is worse than a clear
refusal.
