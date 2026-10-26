# ⚠️ DEPRECATED — Roundtable Multi-Agent Debate

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** Roundtable (multi-agent debate/consensus) is an experimental
feature that is not part of the core JaegerAI product. The core product is a
single persistent AI companion, not a multi-agent debate system.

## Migration Path

### Option 1: Use `jaeger delegate` Commands (Recommended)
For multi-agent workflows, use the built-in delegation system:

```bash
# Ask multiple agents and compare
jaeger delegate run "What's the best approach for X?"
jaeger delegate moa -n 3 "Compare these 3 approaches to X"

# Chain delegates with failover
jaeger delegate run --chain "Research and summarize X"
```

### Option 2: Use External Multi-Agent Frameworks
- **AutoGen** — Microsoft's multi-agent framework
- **CrewAI** — role-based agent teams
- **LangGraph** — graph-based agent workflows

### Option 3: Fork and Maintain Externally
The roundtable code remains in git history. Fork at v0.13.0:

```bash
git checkout v0.13.0 -- jaeger_ai/features/roundtable
```

## What Will Be Removed
- `jaeger_ai/features/roundtable/` — entire directory
- Roundtable imports in `core/frameworks/recovery.py`
- Roundtable profile in WebUI adapter
- Framework registration for "roundtable" runtime

## Timeline
- **v0.13.0** (current): Deprecated, still functional
- **v0.14.0**: Removed from core

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
