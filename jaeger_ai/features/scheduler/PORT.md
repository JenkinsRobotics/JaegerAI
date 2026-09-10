# Scheduler — port notes

## Donors

| Donor | Path | LOC (approx) | Steal |
|---|---|---|---|
| hermes-agent | `cron/jobs.py` | ~4.1k | Job lifecycle, locking |
| hermes-agent | `cron/scheduler.py` | ~8.0k | Tick / deliver_event wiring |
| hermes-agent | `cron/suggestions.py` + `suggestion_catalog.py` | ~0.4k | User-facing job ideas |
| hermes-agent | `cron/incidents.py`, `lifecycle_guard.py`, `monitor.py` | med | Failure taxonomy |
| openclaw | `src/cron/*` | — | Daemon integration ideas |

## Jaeger anchors (keep)

- `jaeger_ai/core/runtime/schedules.py`
- `jaeger_ai/core/runtime/cron_delivery.py`
- `packages/jaeger-agent/jaeger_agent/background/cron.py`

## Next slices

1. On fire → always call `cron_delivery.deliver_text` (close known debt).
2. Suggestion catalog populated from Hermes `suggestion_catalog.py`.
3. Incident / last-error surface for WebUI Tasks.
