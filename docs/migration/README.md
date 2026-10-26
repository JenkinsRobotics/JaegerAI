# JaegerAI Migration Guides

This directory contains migration guides for features and systems that are
changing or being removed in upcoming releases.

## Current Version: 0.13.0 (2026-10-24)

### Breaking Changes in 0.13.0

1. **Personal references removed** — All hardcoded personal names ("Matthew")
   replaced with operator-configurable values. See
   [UNIVERSAL_CLEANUP.md](UNIVERSAL_CLEANUP.md).

2. **YouTube Studio now configurable** — Channel settings moved to
   `~/.jaeger/instances/<name>/youtube.toml`. See
   [YOUTUBE_STUDIO_CONFIG.md](YOUTUBE_STUDIO_CONFIG.md).

3. **Operator configuration system** — New `operator.toml` for personal
   preferences. See [OPERATOR_CONFIG.md](OPERATOR_CONFIG.md).

4. **Scheduler consolidation** — Two scheduler systems unified. See
   [SCHEDULER_CONSOLIDATION.md](SCHEDULER_CONSOLIDATION.md).

### Deprecated Features (Removal in v0.14.0)

The following features are **deprecated** in v0.13.0 and will be **removed**
in v0.14.0. Each has a migration path:

| Feature | Status | Migration Guide |
|---------|--------|-----------------|
| Finance | Deprecated | [FINANCE_FEATURE.md](FINANCE_FEATURE.md) |
| Roundtable (multi-agent debate) | Deprecated | [ROUNDTABLE_FEATURE.md](ROUNDTABLE_FEATURE.md) |
| ARES Migration | Deprecated | [ARES_MIGRATION.md](ARES_MIGRATION.md) |
| Insta360 Camera | Deprecated | [INSTA360_CAMERA.md](INSTA360_CAMERA.md) |
| CalDAV Calendar | Deprecated | [CALDAV_CALENDAR.md](CALDAV_CALENDAR.md) |
| Cost Tracking | Deprecated | [COST_TRACKING.md](COST_TRACKING.md) |
| History Import | Deprecated | [HISTORY_IMPORT.md](HISTORY_IMPORT.md) |
| OIDC Authentication | Deprecated | [OIDC_AUTH.md](OIDC_AUTH.md) |
| Passkeys (WebAuthn) | Deprecated | [PASSKEYS_AUTH.md](PASSKEYS_AUTH.md) |
| Shared Memory (Honcho) | Deprecated | [SHARED_MEMORY.md](SHARED_MEMORY.md) |

### Recommended Upgrade Path

```bash
# 1. Backup your data
jaeger backup

# 2. Run pending migrations (if any deprecated features were in use)
jaeger migrate

# 3. Update to 0.13.0
jaeger update

# 4. Create/update operator config
jaeger config operator init  # Creates ~/.jaeger/operator.toml

# 5. Configure your YouTube channel (if using YouTube Studio)
# Edit ~/.jaeger/instances/jaeger/youtube.toml

# 6. Verify everything works
jaeger doctor
jaeger status
```

## Migration Guides

### For Users
- [UNIVERSAL_CLEANUP.md](UNIVERSAL_CLEANUP.md) — What changed for all users
- [OPERATOR_CONFIG.md](OPERATOR_CONFIG.md) — New operator configuration system
- [YOUTUBE_STUDIO_CONFIG.md](YOUTUBE_STUDIO_CONFIG.md) — Configure your channel
- [SCHEDULER_CONSOLIDATION.md](SCHEDULER_CONSOLIDATION.md) — Scheduler changes

### For Feature-Specific Migrations
- [FINANCE_FEATURE.md](FINANCE_FEATURE.md) — Finance feature removal
- [ROUNDTABLE_FEATURE.md](ROUNDTABLE_FEATURE.md) — Roundtable removal
- [ARES_MIGRATION.md](ARES_MIGRATION.md) — ARES data migration
- [INSTA360_CAMERA.md](INSTA360_CAMERA.md) — Camera integration alternatives
- [CALDAV_CALENDAR.md](CALDAV_CALENDAR.md) — Calendar alternatives
- [COST_TRACKING.md](COST_TRACKING.md) — Cost tracking alternatives
- [HISTORY_IMPORT.md](HISTORY_IMPORT.md) — History import before upgrade
- [OIDC_AUTH.md](OIDC_AUTH.md) — OIDC authentication alternatives
- [PASSKEYS_AUTH.md](PASSKEYS_AUTH.md) — Passkeys alternatives
- [SHARED_MEMORY.md](SHARED_MEMORY.md) — Shared memory alternatives

### For Developers
- [TESTING_MODERN.md](../architecture/TESTING_MODERN.md) — New 4-tier test architecture
- [EXTENSION_GUIDE.md](../EXTENSION_GUIDE.md) — How to build plugins for deprecated features

## Getting Help

- **GitHub Issues:** https://github.com/JenkinsRobotics/JaegerAI/issues
- **Documentation:** `docs/` directory
- **CLI Help:** `jaeger --help`, `jaeger <command> --help`

## Version History

| Version | Date | Major Changes |
|---------|------|---------------|
| 0.13.0 | 2026-10-24 | Universal cleanup, feature deprecation, scheduler consolidation, modern testing |
| 0.12.0 | 2026-10-22 | Gateway daemon, SSE, multi-client support |
