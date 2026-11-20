# Human Needs & Flourishing Engine

User-owned goal, opportunity, outcome, and heartbeat-awareness layer supporting Truth's core mission (*Help humanity, one human at a time*).

## Six Dimensions
- `physical_wellbeing` (Physiological)
- `security` (Safety)
- `belonging` (Love and belonging — daily digest by default)
- `competence_esteem` (Esteem)
- `self_actualization` (Self-actualization)
- `self_transcendence` (Self-transcendence — daily digest by default)

## Modules
- `policy.py` — Quiet hours (`22:00–07:00` default, owner-configurable), non-intrusive digest routing, active-task protection, third-party contact authorization guard.
- `store.py` — SQLite persistence under `operator_state_root() / "human_needs.sqlite3"` (`user_goals`, `user_opportunities`, `user_outcomes`, `human_needs_preferences`, `human_needs_interventions` with unique `dedupe_key` and adaptive dimension weights).
- `heartbeat_loop.py` — Bounded awareness cycle (`Heartbeat -> Understand -> Prioritize -> Plan -> Act -> Verify -> Learn`) integrated into `jaeger_ai/core/runtime/heartbeat.py`, reusing `SqliteDurableTaskStore`, `SqliteWorldStore`, and `PolicyKernel`.
- `tools.py` — Agent tools registered in `jaeger_ai/main.py` (`human_needs_summary`, `human_needs_add_goal`, `human_needs_propose_opportunity`, `human_needs_record_outcome`).
- `routes.py` — Authenticated Gateway API (`/v1/human-needs/*` including `/preferences`, `/heartbeat/run`, `/opportunities/{id}`, `/export`).
