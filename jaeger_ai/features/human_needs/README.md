# Human Needs & Flourishing Engine

User-controlled model of human goals, opportunities, authorized interventions, and measurable outcomes aligned with JaegerAI's mission: *Help humanity, one human at a time.*

## Design Principles

- **Conceptual guide, not a forced ladder:** Six flourishing dimensions (`physical_wellbeing`, `security`, `belonging`, `competence_esteem`, `self_actualization`, `self_transcendence`) help organize goals and surface connections between them. Priorities always belong to the user.
- **Strict epistemic separation:** Every record explicitly distinguishes `objective_measure`, `user_preference`, and `inferred_opportunity`.
- **Non-intrusive boundaries (`policy.py`):**
  - Quiet hours default to `22:00–07:00` (gentle nudges deferred to daily digest).
  - Never pauses or overrides an active user task.
  - Never contacts third parties without explicit authorization.
  - Never manufactures psychological diagnoses.
  - The user can edit, archive, or reject any goal or inferred opportunity and export all data at any time.

## Storage & Routes

- SQLite store at `<operator_state_root>/human_needs.sqlite3` (honors `JAEGER_STATE_DIR` / `JAEGER_HOME`, never writes in-repo).
- Gateway routes (authenticated):
  - `GET /v1/human-needs/summary`
  - `POST /v1/human-needs/goals`
  - `PATCH /v1/human-needs/goals/{id}`
  - `POST /v1/human-needs/opportunities`
  - `POST /v1/human-needs/opportunities/{id}/decide`
  - `POST /v1/human-needs/outcomes`
  - `GET /v1/human-needs/export`
