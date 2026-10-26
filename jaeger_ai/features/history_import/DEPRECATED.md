# ⚠️ DEPRECATED — History Import (General)

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** One-time migration tools for importing from other agents
(Claude, Codex, Gemini, Grok). The ARES-specific import is in `ares_migration`.

## Migration Path

### Before Upgrading to v0.14.0
Run all needed imports:

```bash
# Import from Claude Code
jaeger import history --from claude

# Import from Codex
jaeger import history --from codex

# Import from Gemini
jaeger import history --from gemini
```

### After Import
History is preserved in the canonical session store and searchable via:
```bash
jaeger sessions list
jaeger sessions search "query"
```

## What Will Be Removed
- `jaeger_ai/features/history_import/` — entire directory (except ARES source, moved to `ares_migration`)
- History import tools in `main.py`

## Timeline
- **v0.13.0** (current): Deprecated, still functional
- **v0.14.0**: Removed; import must be done before upgrade

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
