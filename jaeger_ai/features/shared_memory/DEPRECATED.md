# ⚠️ DEPRECATED — Shared Memory (Honcho Integration)

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** Honcho shared memory integration for multi-agent shared
context. This is an experimental feature that requires a self-hosted Honcho
server and is not part of the default deployment.

## Migration Path

### Option 1: Use Local Memory Only (Recommended)
JaegerAI's built-in SQLite memory is sufficient for single-agent use:
- Facts, sessions, notes — all in `~/.jaeger/instances/<name>/memory/`
- Searchable via `jaeger memory` commands

### Option 2: Use Gateway API for Sharing
For multi-agent scenarios, use the Gateway REST API:
```bash
# Agent A writes
curl -X POST http://127.0.0.1:33418/v1/memory/facts \
  -d '{"key": "shared.context", "value": "..."'

# Agent B reads
curl http://127.0.0.1:33418/v1/memory/search?q=context
```

### Option 3: Community Plugin
Maintain Honcho integration as a community plugin.

## What Will Be Removed
- `jaeger_ai/features/shared_memory/` — entire directory
- Honcho imports in `features/host_capabilities/memory_tools.py`
- Honcho imports in `features/reasoning/belief.py`

## Timeline
- **v0.13.0** (current): Deprecated, functional only if HONCHO_API_KEY set
- **v0.14.0**: Removed from core

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
