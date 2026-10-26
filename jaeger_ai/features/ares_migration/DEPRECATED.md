# ⚠️ DEPRECATED — ARES Migration Tools

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** ARES was a predecessor project to JaegerAI. The migration
tools were needed during the transition period (2026-10) but are no longer
part of the core product roadmap.

## Migration Path

### If You Need to Migrate ARES Data
Run the migration tools **before** upgrading to v0.14.0:

```bash
# Export ARES data
jaeger migrate --from ares --output ~/ares-export.json

# Or use the one-time migration on first boot after upgrade
jaeger migrate
```

### After Migration
Your ARES data is preserved in:
- `~/.jaeger/instances/<name>/memory/` — facts, sessions, notes
- Knowledge library entries are preserved

## What Will Be Removed
- `jaeger_ai/features/ares_migration/` — entire directory
- `jaeger_ai/features/history_import/ares/` — ARES-specific source
- Migration tools in `main.py`
- `ares_migration_source` in `core/ares_interop.py` (kept as stub)

## Timeline
- **v0.13.0** (current): Deprecated, still functional
- **v0.14.0**: Removed; migration must be done before upgrade

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
