# Scheduler Consolidation Guide (v0.13.0)

**Date:** 2026-10-24
**Impact:** Users with scheduled jobs or background tasks

## Summary

JaegerAI previously had **two coexisting scheduler systems**:
1. **Legacy Scheduler** (`packages/jaeger-agent/jaeger_agent/background/`) — CronRunner + Board
2. **DurableTaskManager** (`jaeger_ai/core/tasks/`) — GatewayTaskOwner

In v0.13.0, these are being consolidated into a **Unified Scheduler** that
combines the best of both.

## What Changed

### Old Systems

**Legacy Scheduler (Production):**
- `schedule_prompt(cron_expr, prompt, name)` — agent tool
- `CronRunner` — threading-based polling
- Storage: SQLite `schedules` table + JSON `board.json`

**DurableTaskManager (Experimental):**
- `GatewayTaskOwner.submit(goal, context)` — async task submission
- Storage: SQLite `durable_tasks` table in Gateway DB

### New Unified Scheduler

Location: `jaeger_ai/core/tasks/unified.py`

```python
from jaeger_ai.core.tasks import UnifiedScheduler

scheduler = UnifiedScheduler()

# Cron-style scheduling (from legacy)
task = scheduler.schedule_cron("0 9 * * *", "Morning briefing", name="daily-brief")
scheduler.cancel_cron("daily-brief")
jobs = scheduler.list_cron()

# Durable tasks (from new system)
task = scheduler.submit(
    goal="Research and summarize recent AI papers",
    context={"topic": "agent architectures"},
)

# Kanban board (from legacy)
card = scheduler.add_card("Fix login bug", column="backlog")
scheduler.move_card(card.id, "in_progress")
cards = scheduler.list_cards(column="in_progress")
```

## Migration

### Automatic Migration

On first boot after upgrade, the system automatically migrates:

```python
# Runs automatically on Gateway startup
from jaeger_ai.core.tasks.migration import migrate_all
migrated = migrate_all(layout)
# Returns: {"schedules": 5, "board_cards": 12}
```

### Manual Migration

```bash
# Check what would be migrated
jaeger tasks migrate --dry-run

# Run migration
jaeger tasks migrate

# Verify
jaeger tasks list
```

### What Gets Migrated

| Source | Target | Notes |
|--------|--------|-------|
| `schedules` table | `durable_tasks` with `kind=scheduled_job` | Cron expressions preserved |
| `board.json` cards | `task_cards` table | Columns preserved |
| Active `CronRunner` jobs | Running `UnifiedScheduler` tasks | No interruption |

## API Changes

### For Agent Tools

**Old:**
```python
# These tools still work (backward compatible)
schedule_prompt(cron_expr="0 9 * * *", prompt="Morning brief")
list_schedules()
cancel_schedule("Morning brief")
```

**New (recommended):**
```python
# More explicit, returns task object
scheduler.schedule_cron("0 9 * * *", "Morning brief", name="daily-brief")
scheduler.list_tasks(kind="scheduled_job")
scheduler.cancel("daily-brief")
```

### For CLI

**Old:**
```bash
jaeger schedule list
jaeger schedule add "0 9 * * *" "Morning brief"
jaeger schedule cancel "Morning brief"
```

**New:**
```bash
jaeger tasks list
jaeger tasks add --cron "0 9 * * *" --prompt "Morning brief" --name "daily-brief"
jaeger tasks cancel daily-brief
jaeger tasks submit "Research AI papers" --context '{"topic": "agents"}'
```

## Rollback

If you need to rollback to the legacy scheduler:

```bash
# Export current state
jaeger tasks export --output ~/tasks-backup.json

# Disable unified scheduler (env var)
export JAEGER_LEGACY_SCHEDULER=1
jaeger gateway daemon restart

# Re-import if needed
jaeger tasks import ~/tasks-backup.json
```

## Timeline

| Version | Status |
|---------|--------|
| 0.13.0 | Unified scheduler available, legacy still works |
| 0.14.0 | Unified scheduler default, legacy deprecated |
| 0.15.0 | Legacy scheduler removed |

## Questions?

See [README.md](README.md) for the migration guide index.
