# ⚠️ DEPRECATED — Finance Feature

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** This feature was built for a specific operator's personal
finance tracking (Monarch Money integration). It is not part of the core
JaegerAI product and adds significant complexity for a niche use case.

## Migration Path

### Option 1: Use External Tools (Recommended)
Use dedicated finance tools and import summaries via the Gateway API:
- **Monarch Money** — export CSV, use `jaeger` memory tools to store summaries
- **YNAB** — use their API + custom scripts
- **Pocketsmith, Lunch Money** — similar approach

### Option 2: Fork and Maintain Externally
The finance feature code remains in git history. Fork the repo at v0.13.0
and maintain the feature in your fork:

```bash
git checkout v0.13.0 -- jaeger_ai/features/finance
# Add to your fork's tool registry
```

### Option 3: Community Plugin
Submit the finance feature as a community plugin. See
`docs/EXTENSION_GUIDE.md` for the plugin API.

## What Will Be Removed
- `jaeger_ai/features/finance/` — entire directory
- Finance tools in `main.py` (finance_summary, finance_audit, etc.)
- Finance routes in Gateway (`/api/finance/*`)
- MCP tools: `finance_summary`, `finance_audit`
- Database: `~/.jaeger/instances/<name>/memory/finance.db`

## Timeline
- **v0.13.0** (current): Deprecated, still functional
- **v0.14.0**: Removed from core, available as external plugin only

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
