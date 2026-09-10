# Scheduler

Product façade over existing Jaeger schedule CRUD + cron delivery.

## Authority

- Job rows: `jaeger_agent` memory `schedules` table (via
  `jaeger_ai.core.runtime.schedules`)
- Delivery sidecar: `jaeger_ai.core.runtime.cron_delivery`
- Thin ticker: `packages/jaeger-agent/jaeger_agent/background/cron.py`

Do **not** create a second jobs.json. Hermes cron (~16k LOC) is a donor of
patterns (suggestions, incidents, lifecycle guard), not a drop-in.

## This package

- `facade.py` — list/create/pause/resume/cancel + delivery remember/lookup
- `suggestions.py` — stub catalog for future Hermes suggestion port
- `PORT.md` — donor map
