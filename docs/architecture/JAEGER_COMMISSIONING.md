# Jaeger Commissioning

Jaeger sets up Jaeger. A person who knows nothing about AI should be able to
install, answer a few human questions, approve OS permissions when needed, and
reach a working persistent Jaeger.

The sequence is deterministic. Intelligence may choose configuration inside a
stage. It must not invent the overall order.

This document does not replace `JAEGER_LIVE_VALIDATION.md` or
`JAEGER_OPERATIONAL_READINESS.md`. Those remain the live-validation history.

## Product sequence

```
INSTALL → WELCOME → DISCOVER → UNDERSTAND USER → CONFIGURE → AUTHORIZE
       → INTEGRATE → VALIDATE → REPAIR → RESTART → VERIFY → INDEX
       → PERSONA HANDOFF → NORMAL OPERATION
```

Consumer-facing copy never names ReAct, Event Fabric, EffectLedger, embeddings,
MCP, or vector stores. Those details live on `jaeger onboarding status --json`
and the developer/system-status view.

Normal UI may show:

- Setting up your AI…
- Checking this Mac…
- Testing available AI…
- Getting memory ready…
- Checking everything…
- Everything is ready.

## Architecture

Primary object: `CommissioningCoordinator` in
`jaeger_ai/core/instance/commissioning.py`.

It reuses:

- `first_boot.py` durable state
- `first_boot_script.py` OS 1 voice
- `setup_wizard.py` / `onboarding_setup.py` instance writes
- hardware bench + `system_discovery.py`
- provider discovery + `provider_certification.py`
- character / personality / voice
- Authority policy
- readiness / Gateway OWNER resident runtime

The resident Gateway remains the only production EntityRuntime OWNER.
Commissioning does not create a second runtime owner. Temporary
`boot_for_tui()` prepare boots may still warm weights. Final acceptance uses
the resident Gateway.

## State machine

Durable file: `<instance>/first_boot.yaml`. Forward-only unless
`jaeger onboarding reset`. Every transition is idempotent. A crash resumes
from the recorded status and does not replay answered personal questions or
mint a new `entity_id`.

| State | Kind |
| --- | --- |
| `NOT_STARTED` | start |
| `AWAITING_BENCH` / `DISCOVERING_HOST` | host bench (OS 1) |
| `DISCOVERING_SERVICES` | automatic |
| `AWAITING_CHARACTER` | human |
| `AWAITING_SOCIAL` / `AWAITING_HESITANCE` / `AWAITING_VOICE` / `AWAITING_Q2` | human calibration |
| `DISCOVERING_PROVIDERS` | automatic |
| `CERTIFYING_PROVIDERS` | automatic |
| `CONFIGURING_RUNTIME` | automatic |
| `AWAITING_PERMISSIONS` | human, only if extra intent is required |
| `AWAITING_INTEGRATIONS` | human, only if sign-in is required |
| `AWAITING_KNOWLEDGE_APPROVAL` | human, only for extra folders |
| `STARTING_RESIDENT` | automatic — Gateway OWNER |
| `VALIDATING_CORE` / `VALIDATING_TOOLS` / `VALIDATING_MEMORY` / `VALIDATING_BACKGROUND` | automatic |
| `RESTARTING_FOR_PERSISTENCE_TEST` | automatic |
| `VERIFYING_PERSISTENCE` | automatic |
| `INITIAL_INDEXING` | automatic (baseline; remainder async) |
| `INITIALIZING_PERSONA` | OS 1 → persona handoff |
| `COMPLETED` | normal operation |

`AWAITING_BENCH` is the stored name for host discovery so existing OS 1
clients keep working. `DISCOVERING_HOST` is an alias.

## Discovery

`system_discovery.py` produces `HostCapabilityReport`:

- SYSTEM — macOS version, architecture, Apple Silicon generation, unified
  memory, CPU cores, disk, network
- COMPUTE — Metal, local inference
- AUDIO — microphone, output, STT, TTS
- VISION — camera, screen capture, permission state when detectable
- AI — Ollama, LM Studio, Hermes/local endpoints, configured cloud providers,
  installed local model files
- DEVELOPMENT — Git, Python, Xcode, GitHub auth when safely detectable
- JAEGER — Gateway, Bridge, WebUI, Event Fabric, memory store

Missing optional capabilities do not fail commissioning.

## Capability registry

`capability_discovery.py` tracks each capability independently of hardware:

`available`, `configured`, `authorized`, `tested`, `healthy`, `adapter`/`provider`.

Examples: `filesystem.read`, `filesystem.write`, `git`, `github`, `browser`,
`email`, `calendar`, `microphone`, `camera`, `screen`, `notifications`,
`local_ai`, `cloud_ai`, `stt`, `tts`, `shell`, `self_modification`.

## Zero-expertise setup

Normal onboarding does not ask which embedding model, context size, ReAct
model, planner, critic, or endpoint to prefer when Jaeger can test them.

Flow: DISCOVER → TEST → CERTIFY → SELECT BEST VALID CONFIGURATION.

Manual controls remain on the Advanced Setup path (`jaeger setup` /
`setup_wizard.py`). Both paths call the same `create_instance`,
`selected_model_config`, and schemas.

## Provider certification

`provider_certification.py` tests providers by role:

`CHAT`, `REACT`, `PLANNER`, `CRITIC`, `REFLECTION`, `VISION`, `EMBEDDING`.

Persisted: provider, model, role, pass/fail, timestamp, latency, failure
reason, suite version (`commissioning-1`).

Existing evidence remains authoritative until retested:

- `kimi-k2.7-code:cloud` — REACT PASS
- `glm-5.3-flash:cloud` — REACT FAIL

A provider that failed a role is never selected for that role.

The person sees: “I found and tested the AI available on this computer. I
configured the combination that works best.”

## Permissions and progressive authorization

Consumer-facing questions replace `confirm` / `allow everything`.

Example: “Would you like me to help with your files and projects?” becomes
approved filesystem roots plus related capabilities in
`<instance>/authority_policy.yaml`.

Internal policy supports:

- filesystem approved roots
- shell risk mode
- git local commit / git push
- email read / send
- calendar read / modify
- microphone, camera, screen
- self-modification worktree
- protected merge / deployment (always locked unless explicitly granted)

Jaeger never silently grants permissions that require user intent. The
minimum policy (instance directory + Jaeger repository, shell confirm, no
home-directory indexing) is what the OS needs to exist.

TCC prompts are requested only for the chosen interaction mode and approved
capabilities. `request_all()` remains for Advanced Setup and `jaeger doctor`.

Later integrations request authorization when they are first enabled.

## Integration lifecycle

`integration_registry.py`:

DISCOVER → determine whether authentication is required → authorize →
configure → test → register.

Existing plugins and host capabilities are adapted first. New integrations
plug into the same descriptor.

## Knowledge setup

Automatically approved:

- Jaeger repository
- Jaeger documentation
- Agent skills

Other detected folders (Projects, Documents, Notes) are offered, never
indexed without approval. The entire home directory is never an automatic
source. Baseline indexing runs before persona handoff; the rest may continue
asynchronously.

## Resident runtime start

Commissioning writes valid configuration, starts the resident Gateway OWNER,
verifies Gateway status, and runs remaining validation through that resident
Agent. CLI / WebUI / Bridge attach as `ATTACHED_CLIENT` surfaces sharing
`entity_id`, instance, state root, and Event Fabric.

## Validation

`commissioning_validation.py` records actual evidence. Importing a class is
not a PASS.

- CORE — Entity Identity, Event Fabric, memory store, Gateway
- COGNITION — CHAT / REACT (required), planner / critic when enabled
- ACTION — safe tool execution, Authority, objective verification, request
  idempotency
- BACKGROUND — heartbeat, sleep-time scheduler, indexer registration, skill
  registry
- INTERFACES — CLI / WebUI / Bridge attach

## Repair

`commissioning_repair.py`:

FAILURE → DIAGNOSE → can Jaeger safely repair it? → REPAIR → RETEST.
Otherwise request human action.

Safe repairs: missing directories, config defaults, starting an installed
local service, rebuilding indexes, refreshing registries, correcting stale
runtime metadata, selecting a different certified model, restarting a failed
subordinate service.

Never automatic: bypass OS permissions, invent credentials, weaken security,
grant broader Authority, disable verification or EffectLedger, merge to
master, silently install arbitrary software.

## Restart / persistence acceptance

Before `INITIALIZING_PERSONA`, commissioning records `entity_id`, event
sequence, a memory marker, and commissioning state; stops the resident;
starts it again; and verifies:

- same `entity_id`
- same Event Fabric
- sequence continues
- memory marker retained
- onboarding state retained
- Gateway READY
- clients can reattach

## Persona handoff

The installer and the persona remain different speakers. The persona appears
only after runtime health, usable provider roles, usable memory, persisted
permissions, resident Gateway, reachable interfaces, proven restart, and
baseline indexing.

Installer: “Thank you. Please wait as your individualized operating system is
initiated.”

Persona: `*(clears throat)* Hello, I'm here.` then “What do you want to work
on first?”

Nothing technical is appended to that first utterance.

## Recovery

If the process crashes:

- during discovery — resume discovery; do not re-ask character/voice/Q2
- during provider certification — resume certification; keep probe answers
- during configuration — resume configuration; same identity
- during validation — resume validation; repair if safe
- immediately before persistence restart — resume restart; same `entity_id`

`jaeger onboarding reset` clears only the welcome/commissioning record.

## Observability

`jaeger onboarding status` and `--json` report:

- current commissioning stage
- completed stages
- pending human action
- latest validation result
- latest repair attempt
- resident runtime state
- `entity_id`
- provider certifications
- approved integrations
- approved knowledge sources

## Advanced / manual setup

`jaeger setup` remains the explicit manual path. It uses the same instance
write functions and schemas. Commissioning is the intelligent default.

## Success criterion

A nontechnical user can go from a new install to a working persistent Jaeger
without understanding the underlying AI architecture. Jaeger asks only for
things it cannot legitimately determine itself.

**The intelligence is responsible for making the setup disappear.**
