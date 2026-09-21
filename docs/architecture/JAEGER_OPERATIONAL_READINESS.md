# JAEGER OPERATIONAL READINESS

**Branch:** `pinocchio`  
**Do not merge to master.**  
**Specification:** JAEGER PRODUCTION OS IMPLEMENTATION SPECIFICATION (authoritative).

This document describes the resident Jaeger OS as implemented. Prior live-validation failures remain in `JAEGER_LIVE_VALIDATION.md` and are not rewritten.

## Architecture

One resident Agent per instance. Gateway process is the EntityRuntime **OWNER**. CLI, WebUI, Bridge, and MCP are **ATTACHED_CLIENT** surfaces. They share:

```text
entity_id
instance_id
state_root          (instance memory/)
event_store         (memory/entity_events.sqlite3)
latest_event_sequence
```

Cognition modes are selected only by Executive:

```text
PASSIVE | DIRECT_RESPONSE | REACT | DELIBERATIVE_SEARCH | SPECIALIST | SELF_REFINE | SLEEP_TIME
```

## Process topology

```text
launchd / jaeger start --instance <name>
   └── Jaeger Resident Service
         ├── EntityRuntime OWNER
         ├── Gateway :8810
         ├── Event Fabric, Memory, Executive
         ├── Heartbeat / Sensors / Sleep / Index / Maintenance schedulers
         └── children: WebUI :8790, Bridge :8791, CLI attach
```

## State ownership

Canonical `InstanceLayout` (`~/.jaeger/instances/<name>/`):

```text
identity.yaml
config.yaml
memory/
    state.db
    entity_events.sqlite3
    entity_identity.json
    structured_reflections.json
    indexes.sqlite3
skills/
logs/
run/
    entity.resident.lock
    sockets / pid / native-turns.sqlite3
workspace/
```

Operator-global `~/.jaeger/` holds instance catalog, gateway sessions, and launchd metadata. Legacy `~/.jaeger/entity_events.sqlite3` and `entity_identity.json` are copied into instance `memory/` on first OWNER boot (`migrate_legacy_entity_state`).

## Startup

```text
jaeger start --instance jaeger
```

Success requires Gateway `:8810` **and** `GET /v1/runtime/status` `ready=true` with an `entity_id`. Forking a process is not READY.

```text
jaeger stop
jaeger restart
jaeger status
jaeger status --json
```

## Shutdown

`jaeger stop` boots out launchd jobs (supervisor first), stops WebUI, does not claim success if a required service remains.

## Status

`GET /v1/runtime/status` and `jaeger status --json` project:

Agent, Runtime, Provider, Services, Background, Storage, Work.

Each subsystem: `HEALTHY | DEGRADED | BLOCKED | FAILED | DISABLED`. `DISABLED` is not failure.

## Recovery

OWNER boot runs `RecoveryManager.scan_resumable_runs()`:

* orphaned active runs → `blocked` (`owner_lost`)
* pending EffectLedger keys listed, **not** auto-retried

Indeterminate effects stay BLOCKED for operator decision.

## Ports / sockets

| Surface | Port / path |
| :--- | :--- |
| Gateway | `127.0.0.1:8810` |
| WebUI | `127.0.0.1:8790` |
| Bridge / adapter | `127.0.0.1:8791` |
| Native MCP HTTP | `127.0.0.1:8792` |

## Provider assignments

File overlay: `<state_root>/model_capabilities.json`. Seed:

| Model | chat | react |
| :--- | :--- | :--- |
| `kimi-k2.7-code:cloud` | pass | pass |
| `glm-5.3-flash:cloud` | pass | fail |

`ensure_role_client` will not assign a `fail` role. ReAct uses kimi unless `JAEGER_FORCE_MODEL=1`.

## Scheduler priorities

```text
1 foreground human turn
2 completion awaiting delivery
3 active durable foreground task
4 ready board/background task
5 heartbeat
6 sleep-time
7 indexing
8 self-maintenance
```

One maintenance activity at a time. Sleep/index/maintenance yield to foreground cognition.

## Heartbeat

Default production interval: 30 minutes (`config.heartbeat.interval_minutes`). Quiet heartbeat: 0 model calls, event `system.heartbeat`. Not a fake user message.

## Sensors

```yaml
sensors:
  desktop:
    enabled: false
    interval_seconds: 30
```

When enabled, OWNER SensorSupervisor emits `perception.sensed`. Routine events: 0 cognition calls.

## Sleep-time

Trigger: idle, no foreground turn, no higher-priority ready work, interval due. Default `sleep_interval_minutes` 30 (production). One bounded cycle: started → consolidation → contradiction → reflection → goals → skill review → completed.

## Indexing

`jaeger_ai/core/entity/indexing.py`

* FTS5 `indexed_sources` / `indexed_chunks` in instance memory DB `indexes.sqlite3`
* Approved scopes: docs, skills, explicit project dirs
* Hash/mtime skip; max 50 files / 60s per sweep
* Events: `index.started`, `index.source.updated`, `index.completed`
* Retrieval tagged `RETRIEVED_DOCUMENT` (not a belief)

## Maintenance

`jaeger_ai/core/runtime/maintenance.py`

* Isolated git worktree `jaeger-maint/<timestamp>-<task>`
* Never edits the running resident tree
* Never merges to master
* Protected paths (authority, credentials, EffectLedger, autostart, verification disable, merge/release) require operator approval
* Max 3 automatic repair attempts then BLOCKED
* Verified output is a **candidate commit**, not hot-deployed

## Protected self-modification boundaries

Jaeger may not: merge to master, expand permissions, disable verification or Authority, rewrite credentials, auto-deploy a failing candidate.

## Trace instructions

Human turns carry `trace_id` in event provenance (`T<timestamp>` or `request_id`). Inspect:

```text
sqlite3 <instance>/memory/entity_events.sqlite3 \
  "SELECT id, event_type, payload_json FROM entity_events ORDER BY id DESC LIMIT 40;"
```

## Backup / recovery

Backup instance directory (`~/.jaeger/instances/<name>/`) including `memory/`. Restore by copying the directory and `jaeger start --instance <name>`. Identity is `memory/entity_identity.json`.

## Known limitations

* MCP/Bridge processes still instantiate an ATTACHED_CLIENT runtime to record tool events into the shared sqlite; they must not schedule heartbeat/sleep.
* Gateway historically labelled native `complete_task` receipts as `failed`; mapping now treats successful halt+text as `completed`. Requires Gateway process restart to take effect live.
* Crash-resume of the *same* run after SIGKILL is not fully live-proven (Round 3 FAIL remains in the live validation log).
* Reflexion now injects mandatory first-action constraints; live first-tool change still needs the Part 34 mission retest after restart.
* Overnight soak and launchd single-supervisor consolidation are subsequent to resident READY.

## Verdict policy

Only:

```text
NOT OPERATIONAL
OPERATIONAL — MANUAL SUPERVISION REQUIRED
OPERATIONAL — RESIDENT AGENT READY
OPERATIONAL — RESIDENT + AUTONOMOUS MAINTENANCE READY
```

Immediate target: **OPERATIONAL — RESIDENT AGENT READY**.

## Live mission observations (2026-09-21, instance `jaeger`)

After `jaeger restart --no-app --no-containers --instance jaeger`:

| Check | Observed |
| :--- | :--- |
| Start READY gate | `Resident runtime READY entity_id=jaeger-entity-7615957f0fa6` |
| `GET /v1/runtime/status` | `ready=true`, mode=`owner`, resident=`true`, event store under instance `memory/` |
| `jaeger status --json` | same `entity_id` and event store; mode=`attached_client`, resident=`false` |
| Remember APOLLO | fact `tonight_readiness_code=APOLLO`; request status **`completed`** |
| `workspace/tonight.txt` | exists, content `APOLLO` |
| CLI recall | “Tonight's readiness code is APOLLO … workspace/tonight.txt containing exactly APOLLO” |
| request_id replay | `r4-apollo-write` second POST `replayed: true`, original output, no extra human event |
| Write `verification.completed` | **missing** on the file-write turn (tools recorded; independent disk matched) |
| Crash SIGKILL resume | not re-run in this pass (Round 3 FAIL stands) |
| Autostart | implemented (`jaeger autostart enable` defaults to `start --no-app --instance <name>`); not enabled on this machine in this pass |

**Current verdict: OPERATIONAL — MANUAL SUPERVISION REQUIRED**

Resident Gateway is the OWNER; CLI is ATTACHED_CLIENT; identity and Event Fabric are instance-scoped and shared. P0 still open: write-turn objective verification event, live crash-resume, operator-enabled autostart soak.

---

## Round 4 isolated live campaign (do not rewrite the table above)

Isolated instance `commission-r4` / `jaeger-entity-2862e4595e37` / Gateway `:18820`:

* Write-turn `verification.completed` **PASS** (`vrf-8fdb2a6d7f`, `disk_probe`, `objective_verified`).
* Gateway request_id replay **PASS** (`commissioning-idempotency-3ca21cd763b3`, `replayed=true`).
* Gateway OWNER heartbeat + sleep-time event chain **PASS**.
* `write_file` is an EffectLedger `external` effect; controlled resume did not replay A.
* Operator WebUI/Bridge ports are **not** this entity (DISABLED).
* Autostart not enabled on the operator LaunchAgent.

Verdict unchanged: **OPERATIONAL — MANUAL SUPERVISION REQUIRED**.

---

## Round 5 isolated live campaign (do not rewrite the tables above)

Isolated instance `commission-r5` / `jaeger-entity-4211ef75d464` / Gateway `:18821`:

* Write-turn `verification.completed` **PASS** (`vrf-e20bd0b827`, `disk_probe`, `objective_verified`).
* Gateway request_id replay **PASS** (`commissioning-idempotency-61a3ab5930fc`, `replayed=true`).
* `background.completed` **PASS** (`evt-d11a8ba7a988`).
* Gateway OWNER heartbeat + sleep-time **PASS**.
* Autostart enable/disable **PASS** on isolated env; operator `:8810` remained `jaeger-entity-7615957f0fa6`.
* SIGKILL: A not replayed, Gateway became READY after a `get_singleton` deadlock fix; C did not complete on the crash run.
* Index source file was indexed; Gateway retrieval selected repo docs (FAIL).
* WebUI/Bridge for this entity **DISABLED**.
* Reflexion created+retrieved; first-action change not proven.
* `aurora.txt` written; cross-session/post-restart recall of AURORA not proven.

Verdict unchanged: **OPERATIONAL — MANUAL SUPERVISION REQUIRED**.

---

## Round 6 isolated live campaign (do not rewrite the tables above)

Isolated instance `commission-r6` / `jaeger-entity-f0e310f53564` / Gateway `:18822` / WebUI `:18790` / Bridge `:18791`:

* Index extra-source retrieval **PASS** (`evt-6a054f549daa`, phrase `NEBULA-COMMISSIONING-INDEX`).
* SIGKILL same-run C-completion **PASS** (run `1af0b8b6bec2442d`, A not replayed, `crash-c.txt`=`C-DONE`).
* Reflexion first-action **PASS** (`read_file` → `write_file`, `evt-0fcffb5e061b` / `evt-dfc84b6404dd`).
* AURORA recall and post-restart continuity **PASS**.
* WebUI/CLI/Bridge/Gateway same `entity_id`; ATLAS continuity **PASS**.

**Current verdict: OPERATIONAL — RESIDENT AGENT READY**
