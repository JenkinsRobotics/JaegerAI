# ⚠️ DEPRECATED — Cost Tracking

**Status:** DEPRECATED as of 2026-10-24. Scheduled for removal in v0.14.0.

**Why deprecated:** LLM cost tracking is useful but should be a generic
observability feature, not a dedicated module.

## Migration Path

### Option 1: Use Gateway Observability
The Gateway already tracks token usage per session. View with:

```bash
jaeger status --json | jq '.sessions[].tokens'
```

### Option 2: Use Provider Dashboards
- **Ollama Cloud** — https://ollama.com/account/usage
- **OpenAI** — https://platform.openai.com/usage
- **Anthropic** — console.anthropic.com

### Option 3: Community Plugin
Maintain as a community plugin with budget alerts.

## What Will Be Removed
- `jaeger_ai/features/cost_tracking/` — entire directory
- Cost tracking in `core/runtime/subagents.py` (budget checks)
- Cost tools in `main.py`

## Timeline
- **v0.13.0** (current): Deprecated, still functional
- **v0.14.0**: Removed from core

## Questions?
Open an issue on GitHub: https://github.com/JenkinsRobotics/JaegerAI/issues
