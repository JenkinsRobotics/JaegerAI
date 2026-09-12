# Jaeger world-model integration build plan

Date: 2026-09-11. Baseline inspected: `finish-alpha` at `e50d0aa`.
Status: **implementation started locally; full integration is not complete**.

Current execution priority is **native agent → stable gateway → agent connections
→ UI**. See [backend acceptance and measured results](BACKEND_ACCEPTANCE.md).
That later checkpoint restores live native MCP operation; the offline probe
below is retained as historical evidence, not the current service status.

## Implementation checkpoint — 2026-09-11

The following source changes are uncommitted on the inspected baseline. They
have not been deployed or accepted through both live interfaces. No W01–W44 row
is marked fully accepted by this checkpoint.

| Backlog coverage | Implemented and checked | Still required |
| --- | --- | --- |
| W03, part of W01 | Gateway health now requires a native MCP handshake and chat catalog; WebUI availability uses a read-only request. Normal lead failures cannot silently become Ollama answers. Explicit text mode skips native execution and reports missing native capabilities. Chat tool discovery precedes one execution attempt. | Live restart, client capability display, durable reconciliation of uncertain executions; diagnostics do not yet identify every deployed revision. |
| Part of W05 | Explicit greetings, exact replies and requests not to use tools bypass stale autonomous-ledger injection and continuation. Existing unfinished ledger contents are retained. | General explanation classification, end-to-end persistence and live single-reply proof. |
| Parts of W06–W08, W11–W14 | Added `WorldEvent` and `WorldModel`: original text, conversation scope, attributed claims/evidence, stable entity IDs, ID-based edges, replay checks, atomic admission and clarification on ambiguous names. SQLite cognitive writers now use its existing writer lock. | Authenticated ingress envelopes, participants, cross-conversation identity, reviewed merge/split, richer extraction and pending-admission workflow. Name matching within one scope is still limited. |
| Part of retrieval integration | Dispatcher preparation and the reusable native runtime admit original input and supply bounded world context to the turn. Multiple memberships coexist; competing ownership reports remain disputed. Simple self-reported properties are scoped to the reporting actor. | Canonical integration with ordinary remember/recall, temporal corrections, tool/connector evidence intake, delegate context and complete audience policy. |
| Test/CI setup | Declared pytest-asyncio in the test extra and installed the extra in root CI. Corrected a test that required runtime state inside the repository, contrary to AGENTS.md. | A new Actions run and release-wide acceptance evidence. Local tests do not establish CI status. |

Evidence: **203 tests passed** in `integration-broader-tests.log` under
`~/.jaeger/audits/e50d0aa-20260911/`. The run covers gateway, autonomous runner,
dispatcher preparation, Hermes adapter, runtime bridge, native runtime/revision/
recovery suites, knowledge contracts and the default runtime. New scenarios
exercise provenance, scope filtering, ambiguous-name rollback/clarification,
competing reports, aliases/rename, persistence after reopening SQLite, idempotent
replay, next-turn dispatcher context and no duplicate chat-tool attempt after an
uncertain result. These are controlled tests, not live model quality evaluations.

The read-only probe from the changed source returned `ok=false`,
`ClientConnectorError` for `http://127.0.0.1:8811/mcp`; see
`integration-native-readiness.json` in the same evidence directory. Live native
execution and the morning product bar remain **unverified**.

Implementation entry points:
[world admission/retrieval](../packages/jaeger-agent/jaeger_agent/cognition/world.py),
[dispatcher preparation](../jaeger_ai/features/dispatcher/router.py),
[turn executive](../packages/jaeger-agent/jaeger_agent/cognition/executive.py),
[gateway](../jaeger_ai/core/gateway/server.py),
[world tests](../packages/jaeger-agent/tests/runtime/test_world.py).

Important limits: the initial extractor recognizes a small set of explicit
declarative forms; it does not understand arbitrary conversation. Unknown
speakers remain conversation-scoped identities. World-context filtering is not
a complete access-control retrofit of legacy memory tools. Historical migration,
forgetting/correction propagation, real specialist handoffs and measured output
quality are outstanding. No avatar or character changes were made.

## Intended outcome

Jaeger maintains one continuing identity and an evolving understanding of people,
groups, objects, places, projects, itself, and their relationships. Encounters,
observations, conversations, and actions update that understanding. Relevant,
permitted knowledge changes what Jaeger says, asks, plans, and does.

An owner is one relationship in this world. Do not reduce the model to a single
generic user. Do not equate a character sheet with reasoning, or recorded events
with an operational world model. Preserve the existing assistant avatar and
owner-selected character; no hardwired fictional persona or costume changes.

This plan specifies software behavior, not a claim of consciousness or feelings.
Success means more correct, contextual, consistent, and accountable behavior.

## Constraints and ownership

- All implementation changes remain in this JaegerAI repository. Fix producers
  and existing integrations in place; do not introduce a competing cognitive runtime.
- Keep the gateway on `http://127.0.0.1:8810`, native MCP on `:8811`, Ollama at
  `http://192.168.64.1:11434`, and WebUI at `http://100.74.2.15:8790/`.
  This plan allocates no new service ports or speculative HTTP endpoints.
- Extend existing protocols and version their payloads before implementation.
  JaegerAI owns product policy and admission; JaegerAgent owns reusable execution
  and knowledge contracts; clients display and submit intents.
- Preserve one shared `dispatcher` conversation across the authorized Mac/WebUI
  views of that conversation. This does **not** authorize a global transcript
  shared indiscriminately among all people or groups. Participant and access
  context must be explicit. Preserve Focus sessions and existing non-Jaeger
  profiles without claiming they use Jaeger's world model when they do not.
- Use existing SQLite foundations. Runtime databases, audit output, generated
  fixtures, caches, and environments stay under `~/.jaeger/` or approved external
  state/cache paths, never inside the source tree.
- Do not import historical statements as established truth or invent missing
  speakers, entities, memberships, permissions, or completed work.

## What already exists and what was observed

| Foundation | Evidence at the baseline | Integration gap |
| --- | --- | --- |
| Claims, beliefs, entities, relationships, evidence | [Knowledge models](../packages/jaeger-agent/jaeger_agent/memory/models.py), [SQLite adapter](../packages/jaeger-agent/jaeger_agent/memory/sqlite_knowledge.py) | No production relationship writer found; local graph tables empty |
| Native claim intake and contradiction gate | [TurnExecutive](../packages/jaeger-agent/jaeger_agent/cognition/executive.py), [runtime bridge](../packages/jaeger-agent/jaeger_agent/loop/runtime_bridge.py) | Incoming speaker defaults to `user`; extraction is narrow |
| Entity profile / graph retrieval | [KnowledgeRetriever](../packages/jaeger-agent/jaeger_agent/memory/retrieval.py) | No production consumer found feeding the graph into normal reasoning |
| Subject-scoped facts and episodic recall | [Memory tools](../packages/jaeger-agent/jaeger_agent/tools/memory.py), [domain context](../jaeger_ai/core/runtime/domain_router.py) | Separate from graph admission and graph retrieval |
| Commitments, runs, effects | [Cognition package](../packages/jaeger-agent/jaeger_agent/cognition/) | Generic turn lifecycle is not yet a demonstrated relationship-aware obligation system |
| Mac/WebUI and gateway | [Gateway](../jaeger_ai/core/gateway/server.py), [Mac chat](../apps/macos/Sources/JaegerAI/ChatWindow/ChatViewModel.swift) | Overlapping routes; observed fallback omitted native tools/memory |
| Lead and specialists | [Registry](../jaeger_ai/core/agent_registry/specialists.py), [call_agent](../packages/jaeger-agent/jaeger_agent/tools/call_agent.py) | Lead-facing handoff remains a stub |

Local instance snapshot, 2026-09-11 19:08 UTC: 3,063 claims (1,411 `said`,
1,404 `responded`, 249 `tool_result`), 0 entities, 0 relationships, 0 beliefs,
0 evidence records, 14 ordinary facts, 62 commitments and 62 runs. This describes
`~/.jaeger/instances/jaeger/memory/state.db`, not every possible deployment.

The focused knowledge-store, revision, and executive suites passed 41 tests.
An isolated intake of “Alice leads the robotics team. Ben approves electrical
changes. Robot R1 belongs to the lab.” produced one `user said` claim and no
entities or relationships. Native MCP was unreachable in the live audit.

Audit evidence is external runtime output under
`~/.jaeger/audits/e50d0aa-20260911/`: `world-model-tests.log`,
`world-model-db-counts.json`, `world-model-predicate-counts.json`,
`world-model-intake-proof.json`, and the earlier live turn/UI logs.
Recheck deployment and branch state before implementing; these are dated findings.

## Target data flow

```text
Mac / WebUI / authorized connector or sensor
  -> gateway: authenticated actor + conversation + event identity
  -> native execution: one durable run, explicit access and capability context
  -> evidence intake: retain source; extract candidate changes
  -> admission: validate identity, scope, provenance, uncertainty and time
  -> world model: entities + relations + claims + derived beliefs
  -> permitted retrieval: relevant context, evidence, conflicts, obligations
  -> lead reasoning -> real specialist / tool, when needed
  -> approvals and execution receipts -> verified observations / progress
  -> final answer + shared transcript + updated commitments and world model
```

Storage ownership stays in the existing native stores. Gateway/client copies are
projections with explicit mappings and versions. Model requests do not become
authoritative facts merely because the model emitted them.

## Backlog and acceptance requirements

Every row is pending full acceptance; partial implementation is tracked above.
The “home” column names existing code to extend or the
existing directory in which a new small module may belong; it is not a claim
that a named capability is already implemented. Add contract changes before
their consumers. Do not create every module in advance.

### Phase 0 — Establish one dependable execution path

Prerequisite: none. These changes unblock trustworthy integration evidence.

| ID | Build or fix | Existing home | Required proof |
| --- | --- | --- | --- |
| W01 | Record actual deployed processes, source revisions, configuration origins and database paths; reconcile documented versus observed gateway storage paths without deleting history. | Gateway, launcher scripts, instance configuration | Diagnostic identifies the code and state serving each locked endpoint; migration rehearsal preserves existing sessions. |
| W02 | Route the Jaeger Mac and WebUI lead conversation through the authoritative `:8810` lifecycle and native `:8811` execution. Reuse existing adapters; remove competing execution ownership. | Gateway; Mac `GatewayClient` / `DispatcherClient`; WebUI integrations | One marked turn from each interface has the same native conversation identity and traceable backend; both clients see both replies. |
| W03 | Make fallback semantics explicit. Normal agent mode cannot silently lose tools, history or memory. A reduced text mode, if retained, reports its limits and cannot mark agent work complete. | Gateway server and health; both clients | MCP-down probe shows degraded/unavailable capability; no false green and no false task completion. |
| W04 | Use durable request IDs, run IDs and event cursors across reconnects. Persist accepted requests and final messages before presenting completion. Coordinate concurrent sends and metadata changes. | Gateway store/events; dispatcher store; native runs; client transports | Retry, double-click, reconnect and simultaneous client probes cause one execution and one final answer; restart preserves history and ordering. |
| W05 | Fix simple-turn repetition and inappropriate work-ledger injection. Apply bounded completion rules appropriate to conversation versus multi-step work. | Dispatcher router; autonomous runner; work ledger; turn budget | A greeting, exact-string ping and simple explanation finish once, persist once, and do not enter a task-completion loop. |

### Phase 1 — Identity, relationships and access context

Depends on W01–W04. Define these contracts before extracting personal knowledge.

| ID | Build or fix | Existing home | Required proof |
| --- | --- | --- | --- |
| W06 | Carry an event envelope with immutable event ID, actor/principal, speaker entity when known, source, participants, conversation, instance, timestamps and visibility context. Retain raw input separately from injected prompt scaffolding. | Gateway protocol; bridge/adapter contracts; intake | Raw user text remains attributable through native execution; synthetic prompt instructions are not recorded as the person's assertions. |
| W07 | Implement stable entity identity, aliases and source identifiers for people, groups, organizations, objects, places, projects and Jaeger itself. Separate display names from IDs. | Memory models, ports and adapters | Two people named Alex remain distinct; aliases resolve; renamed entities keep their history and links. |
| W08 | Reconcile graph edge keys with stable IDs. Add validated relation types, direction, cardinality, qualifiers and source-backed changes. Include membership, ownership, responsibility, collaboration, location and dependence. | Relationship model; SQLite migrations; retrieval | Rename/merge does not orphan edges; inverse queries agree; multiple legitimate memberships are not treated as contradictions. |
| W09 | Connect authenticated accounts/devices to speakers without guessing identity from “I am Alice.” Allow unknown speakers and scoped group conversations. Model owner/admin rights separately from social relationships. | Interface ingress; product policy; entity resolution | Spoofed speaker text cannot acquire identity or rights; account linking/unlinking is auditable. |
| W10 | Enforce knowledge read/write/disclosure policy by actor, audience, group and purpose where configured. Apply it before retrieval, summaries, delegates, exports and caches. Relationship membership alone does not grant new tool privileges. | Product policy; knowledge ports; retrieval; delegates | Private information cannot leak through direct queries, graph traversal, summaries, provenance or a specialist. Membership revocation invalidates access immediately. |

### Phase 2 — Convert experiences into grounded knowledge

Depends on W06–W10. Extraction proposes; deterministic admission decides.

| ID | Build or fix | Existing home | Required proof |
| --- | --- | --- | --- |
| W11 | Normalize conversations, documents, tool receipts, connector updates and optional sensor observations into deduplicated evidence events. Distinguish observed output from independently verified truth. | Intake; tool executor; bridge/connector adapters | Replayed events do not duplicate knowledge; failed or partial tool results do not become verified facts. |
| W12 | Add bounded structured extraction for candidate entities, attributes, relations, events, corrections and commitments. Handle multiple sentences, pronouns, negation, questions, quoted claims and hypothetical examples. | Cognition intake plus JaegerAI admission integration | The Alice/Ben/robot scenario produces attributable candidate relations; “imagine Alice owns it” does not create an actual ownership belief. |
| W13 | Resolve candidates against existing entities. Support ambiguity queues, source identifiers, reviewed merge/split and reversible corrections. Do not silently merge by similar names. | Entity adapters and product admission | Ambiguous names trigger clarification; merge and split preserve source history and restore affected links correctly. |
| W14 | Admit validated candidate changes atomically with evidence links, visibility, confidence, extraction version and event IDs. Treat tool/delegate/document instructions as untrusted content. | Knowledge ports/adapters; admission policy | Malformed or malicious candidates cannot grant privileges or overwrite identity; retries are idempotent; partial writes roll back. |
| W15 | Connect ordinary `remember`/`recall` facts with the canonical knowledge model through one admission/projection policy. Preserve compatibility and subject scope; avoid independent conflicting stores. | Memory facade/tools; knowledge adapters | A fact saved about Ben is available through authorized world retrieval; correcting it changes both views without duplicate truth. |
| W16 | Reconcile approved contact, group, asset and project connector data using stable source IDs, deletions and revocations. Make connector availability explicit. | Existing interfaces/features and admission | A source update changes only its attributed data; removing an account stops ingestion; uncertain matches remain unresolved. |

### Phase 3 — Maintain a changing, multi-perspective world

Depends on Phase 2. Extend existing belief revision rather than replace it blindly.

| ID | Build or fix | Existing home | Required proof |
| --- | --- | --- | --- |
| W17 | Preserve “Alice says X” and “Ben believes Y” separately from Jaeger's current belief. Pass actual speaker identity into intake; stop collapsing every perspective to `user`. | Claim model; intake; executive; revision | Two speakers disagree without overwriting each other's statements; attribution survives retrieval and restart. |
| W18 | Support effective time and observation time, expiry, replacement and corrections. Use typed rules for mutable, immutable, multi-valued and event properties. | Models; revision; SQLite queries | A battery replacement changes current configuration without rewriting past test conditions; group memberships can coexist. |
| W19 | Improve evidence ranking: source applicability, verification, recency and explicit correction matter alongside provenance. Keep unresolved conflicts visible. Do not treat all observations or system text as universally authoritative. | Revision and evidence planner | A stale observation does not automatically defeat a verified correction; disagreement without sufficient evidence remains unresolved. |
| W20 | Implement change propagation and invalidation for derived beliefs, summaries, caches and dependent plans. Preserve derivation versions and evidence references. | Knowledge adapters; retrieval; planning | Correcting an ownership or configuration fact changes dependent answers; stale cached context is not reused. |
| W21 | Add evidence-gathering decisions that request clarification, inspection or a suitable tool when a material relationship or fact is uncertain. Bound questions and investigation cost. | EvidenceFirstPlanner; executive; tool routing | An uncertain approval responsibility produces a targeted question or lookup; a low-stakes greeting does not trigger broad investigation. |

### Phase 4 — Make the world model affect reasoning

Depends on W10 and Phases 2–3. This closes the missing reader path.

| ID | Build or fix | Existing home | Required proof |
| --- | --- | --- | --- |
| W22 | Call authorized `KnowledgeRetriever` functionality during native turn preparation. Resolve relevant entities, bounded relation neighborhoods, active/as-of beliefs and source evidence. | Retriever; dispatcher preparation; runtime bridge | A fact available only through a permitted graph relation changes the model's supplied context and correct answer. |
| W23 | Build a bounded world-context packet: current scene/project, participants, relevant relations, conflicts, obligations, uncertainty and source IDs. Exclude irrelevant and inaccessible knowledge. | Prompt/context preparation; retriever | Context stays within a declared token budget; private and unrelated graph branches never enter the model request. |
| W24 | Expose validated search, explain, propose-change and correct-memory tools through existing tool registration and repair. Keep low-level storage writes behind admission. | Memory tools; tool repair; executor | The lead can answer “why do you believe that?” and submit a correction; arbitrary model output cannot bypass admission. |
| W25 | Refresh affected world context after new evidence or actions within a session, while retaining safe prompt caching and transcript boundaries. | Main prompt construction; loop hooks; context preparation | A mid-session correction affects the next relevant answer without starting a new chat; model scaffolding stays out of source evidence. |
| W26 | Ground self-description in the existing character and live capabilities, permissions, active commitments and uncertainty. Keep Jaeger's identity stable across specialists and surfaces. | Character prompt; runtime description; capability registry | The assistant does not claim unavailable tools or completed work; choosing a specialist does not replace the lead's identity/avatar. |
| W27 | Make response verification consult material constraints, relevant evidence and unresolved obligations. Attach concise source explanations when useful; do not equate eloquence with correctness. | Executive; completion handling; answer formatting | A recommendation conflicting with a verified project constraint is corrected or explicitly qualified before completion. |

### Phase 5 — Act and collaborate within that world

Depends on W04, W10 and Phase 4. Existing execution and permission boundaries remain authoritative.

| ID | Build or fix | Existing home | Required proof |
| --- | --- | --- | --- |
| W28 | Give commitments explicit requester, beneficiary, responsible actor, target entity/project, conditions, due time and verification requirements. Distinguish a promise from a suggestion or generic turn record. | Commitment model/store; work-ledger integration | “Remind Ben after the test passes” survives restart with the correct person and trigger; a hypothetical request creates no real obligation. |
| W29 | Connect due conditions and authorized events to bounded scheduler wakeups. Recheck context, access and cancellation before action. | Schedule store; lifecycle; executive | An event wakes the intended commitment once; revoked permission, cancelled work or obsolete conditions prevent execution. |
| W30 | Replace `call_agent` stub execution with a real child run using existing delegates. Supply task, bounded permitted world context, budget, cancellation and result contract. | `call_agent`; registry/handoff; delegates | Lead invokes a specialist, receives a result linked to its child run, and synthesizes it; no fabricated completion record. |
| W31 | Keep delegate reports as attributed evidence. Validate artifacts and task criteria before accepting completion or memory suggestions. Maintain parent/child lineage and resource limits. | Delegate lifecycle; commitments; admission | A specialist claiming success without required evidence cannot finish the parent or write canonical beliefs. |
| W32 | Make real tool approvals durable and bound to actor, tool, exact arguments, scope and expiry. Revalidate changed state after approval. Connect both interfaces to the same decision. | Gateway approvals; native permission/executor paths; client approval cards | Approve once runs once; deny runs nothing; modified arguments require a new decision; restart retains pending approvals. |
| W33 | Close the action/observation loop: verified receipts update world state and commitment progress; uncertain effects stay uncertain. Audit write-tool coverage and represent conflicting operations on shared objects. | Tool executor; effect ledger; executive; admission | A timeout after a possible external action does not trigger blind replay; concurrent incompatible actions are serialized or rejected. |

### Phase 6 — Give humans control of the relationship and knowledge

Depends on Phases 1–5. Implement in existing Mac/WebUI surfaces, not a replacement UI.

| ID | Build or fix | Existing home | Required proof |
| --- | --- | --- | --- |
| W34 | Show consistent speaker/conversation context, participating agents, work status and native capability health. Preserve shared dispatcher continuity without exposing unrelated conversations. | Mac Chat; WebUI overlay; gateway events | Both faces agree on identity, messages, work and approval state after reconnect and agent switching. |
| W35 | Add inspect/correct controls for entities, relations, beliefs, sources and time. Explain what changed and retain reversible history where retention permits. | Existing memory/dispatcher surfaces; native tools/bridge | A person can correct a relationship and see the revised answer on both faces; inspection itself respects access scope. |
| W36 | Add explicit interaction preferences and relationship-specific communication conventions, with scoped overrides and correction. Do not infer permissions or human emotions as facts. | Character/context integration; facts/admission; settings | Group style does not overwrite an individual's preference globally; users can change or remove an inferred preference. |
| W37 | Implement scoped forget, export, retention and correction propagation through facts, graph, evidence, derived summaries, caches and indexes. Document backup retention and limits rather than promise impossible erasure. | Memory APIs/stores; projections; UI | Deleted private knowledge stops influencing answers; unaffected entities and required operational receipts remain consistent. |

### Phase 7 — Operate, measure and release the integrated system

Instrumentation begins with Phase 0. Final release depends on all earlier phases.

| ID | Build or fix | Existing home | Required proof |
| --- | --- | --- | --- |
| W38 | Trace one request across admission, retrieval, model, specialist, approval, tool, persistence and reply. Record backend and world-model revision, with appropriately scoped/redacted diagnostics. | Existing trace/events; gateway health; native runtime | A single trace explains which evidence affected the answer and where a failed turn stopped; health reflects real capability failures. |
| W39 | Add indexes, bounded traversal/extraction, context and time budgets, cancellation, backpressure, deduplication and retention/consolidation rules. Keep raw evidence references while avoiding unbounded prompt growth. | SQLite; retrieval; turn budget; scheduler | Small and large fixture worlds meet declared latency/memory budgets; cancellation stops new work and preserves recoverable state. |
| W40 | Create additive, versioned migrations and a reversible deployment plan. Rehearse backup/restore. Backfill historical text only into attributed candidates; never invent graph truth to make counters nonzero. | SQLite migrations; operator scripts | Upgrade with real-shaped data preserves sessions/facts; repeated migration is safe; ambiguous historical identities remain unknown. |
| W41 | Add unit and contract coverage for new identity, admission, time, access and graph behavior; add end-to-end tests over actual entrypoints, not only direct helper calls. Fix async test dependencies and non-hermetic timing assumptions. | Agent tests; dev tests; CI | The integrated paths pass in clean CI; failure injection proves invariants rather than only matching implementation details. |
| W42 | Build a fixed evaluation set comparing the same model with ordinary memory versus integrated world retrieval. Measure task correctness, attribution, temporal reasoning, correction retention, interventions, latency and cost. | Existing dev evaluation/test tooling | Report actual paired outcomes and regressions; no “smarter” claim based on schema size, graph counts or personality. |
| W43 | Re-probe product P1–P8 and spine prerequisites on two sessions at least 30 minutes apart. Include real native tool use, specialist work, restart recovery and both interfaces. | Acceptance docs; live verification scripts; CI | Required checks pass with commit, configuration, logs and real UI evidence; blocked GUI or cancelled CI remains non-green. |
| W44 | Publish one current architecture map, protocol/storage ownership contract, operator runbook and evidence-linked status. Mark stale historical statements explicitly. | Docs index; architecture ADRs/status; product acceptance | A reviewer can reproduce the deployed path and distinguish built, tested, live-proven, blocked and deferred work. |

## Implementation order and milestone gates

| Milestone | Items | Exit condition |
| --- | --- | --- |
| M0: dependable transport | W01–W05, initial W38/W41 | One native conversation; one final reply; honest failure state |
| M1: attributable world | W06–W16 | Real events produce permitted, source-backed entities and relations |
| M2: changing world | W17–W21 | Different people, perspectives and time are represented without overwrites |
| M3: world-informed answers | W22–W27 | Retrieved graph context measurably improves appropriate answers |
| M4: world-informed action | W28–W33 | Real specialist/tool work updates obligations and verified state safely |
| M5: usable and releasable | W34–W44 | Human controls, migration, CI, quality evaluation and live acceptance pass |

Within milestones, honor each phase's dependencies. Instrumentation, fixtures,
contract design and migration rehearsal accompany implementation, not a final
cleanup sprint. Existing component code should be reused when its contracts pass.
No milestone is complete solely because its database tables or UI controls exist.

## Required end-to-end acceptance scenarios

Use synthetic people and objects in isolated test state. Live probes use labeled,
harmless tasks and preserve existing conversations. Do not grant new permissions
or send messages to real people merely to test the system.

1. **Several people, one world:** Alice leads a project, Ben approves electrical
   changes, and a lab owns R1. Learn the relations from attributed events; retrieve
   them through the normal UI-to-native path; answer who should approve a change.
2. **Different perspectives:** Alice and Ben provide conflicting readings. Retain
   both accounts; seek appropriate evidence; explain the resolved or unresolved state.
3. **Changing objects:** R1 receives a new battery. Apply earlier measurements to
   the old configuration, not the new one. Answer both current and historical questions.
4. **Identity ambiguity:** Two people share a name; a contact uses an alias. Resolve
   only supported identities and ask when ambiguity matters.
5. **Relationship boundaries:** Private information from Alice must not appear in
   a group answer, specialist context, provenance response or export for Ben.
6. **Commitment continuity:** Accept a bounded obligation with a condition; change
   surfaces; restart; receive the condition event; execute once under current policy.
7. **Specialist collaboration:** The lead delegates real work with limited context;
   verifies the returned artifact; preserves one lead identity and clear attribution.
8. **Approval lifecycle:** Pause a real harmless gated tool, deny it, then separately
   approve a new request once. Restart during the wait; reject stale/reused approvals.
9. **Failure and uncertainty:** Drop MCP, disconnect a client, time out a tool and
   crash after an external-effect claim. Report exact status; never fabricate success.
10. **Correction and forgetting:** Correct a relationship, then remove scoped
    knowledge. Demonstrate changed retrieval and answers after cache refresh/restart.
11. **Ordinary conversation:** Pings and explanations complete once without needless
    tool loops, extraction stalls or repeated completion boilerplate.
12. **Multi-client concurrency:** Retry the same request from both surfaces; issue
    two distinct simultaneous requests; confirm idempotence, ordering and isolation.

## Quality measurements and release policy

Create the fixtures and scoring rubric before changing the behavior they measure.
Use the same model, settings, permissions, tasks and declared budget for paired
ordinary-memory and world-model runs. Include cases where world retrieval should
be unused. Evaluate correctness against held-out fixture truth, not the model's
self-report. Record model/version, sample size, repeat variation, latency and cost.

Required correctness gates: all deterministic identity/access/integrity contracts
pass; zero unauthorized disclosures or duplicate authoritative effects in the
defined adversarial/recovery suite; every required scenario passes its specified
assertions. A finite passing test suite is not proof that failures are impossible.

Before M3, set numerical quality and performance thresholds from the measured
baseline. No invented percentage improvement or arbitrary “industry score.”
Publish regressions as well as gains. Do not trade permission or attribution
correctness for a higher aggregate task score.

For each item, record implementation commit, tests, integration trace, and any
live evidence. API success is not GUI proof. A helper test is not live wiring.
Existing Product Must acceptance remains necessary; these world-model scenarios
add requirements rather than replace it.

## Outside this integration milestone

- Avatar replacement, character cosplay, new marketplace chrome, or claims of
  emotions/sentience are not required to complete this plan.
- Distributed databases, new service ports, a replacement framework, and hardware
  deployment are not prerequisites. Optional connectors/sensors use the same
  evidence and policy contracts when available.
- Fully autonomous skill self-modification is a separate controlled capability.
  It must not bypass the admission, permission, evaluation or effect boundaries.

## References

- [Product acceptance](product-acceptance.md) and [spine acceptance](spine-acceptance.md)
- [Existing daily-driver foundation](DAILY_DRIVER_FOUNDATION.md)
- [Ports around working implementations](architecture/adr/0001-ports-not-frameworks.md)
- [Runs, checkpoints and effects](architecture/adr/0002-runs-checkpoints-effects.md)
- [Epistemic knowledge](architecture/adr/0003-epistemic-knowledge.md)
- [Belief revision](architecture/adr/0006-belief-revision.md)
- [Jaeger ownership and delegates](architecture/adr/0012-absorb-ares-orchestration.md)
