# JAEGER_LIVE_VALIDATION.md

**Date:** 2026-09-21  
**Branch:** `pinocchio`  
**Question:** Does Jaeger itself now behave like the Universal Persistent Agent Architecture in real operation?  
**Answer:** On the production CLI path of this branch, Jaeger is a persistent ReAct agent with a real event kernel, identity, authority gate, and fail-closed degraded mode. It is not yet a coherent long-lived agent OS. Several UPAA boxes exist in code and unit tests and do not run when a user actually launches Jaeger.

This report is from live production entrypoints (`./jaeger --instance …` one-shot and `--daemon`), plus gray-box inspection of the event DB, memory SQLite, and disk. Unit tests and `EntityRuntime` method calls were not treated as proof of user-facing behavior.

**Harness:** isolated product instance, not the operator's live `~/.jaeger/instances/jaeger`.

| Item | Value |
| :--- | :--- |
| State dir | `/tmp/jaeger-pinocchio-live-validation/state` |
| Instance | `pinocchio-val` |
| `entity_id` | `jaeger-entity-7ebe2aeb1cbe` |
| Cognition (working) | `ollama` / `kimi-k2.7-code:cloud` |
| Cognition (product default on this machine) | `glm-5.3-flash:cloud` — failed ReAct (`thinking_exhausted`) |
| Skills at boot | 188 tools, 2 tool-providing skills, 105 recipe skills |
| Event fabric after campaign | 602 events in `entity_events.sqlite3` |
| Repo pollution | none (no runtime DB inside the git tree) |

The already-running operator fabric (`jaeger status`: Gateway :8810, Bridge, WebUI, Desktop App) still has **no** `~/.jaeger/entity_events.sqlite3`. That long-lived process is not this kernel. Identity file `~/.jaeger/entity_identity.json` exists (`jaeger-entity-7615957f0fa6`) with no event log beside it.

---

## Scorecard

| Capability                | Result | Evidence | Defect |
| ------------------------- | ------ | -------- | ------ |
| Identity continuity       | PASS   | Same `entity_id` `jaeger-entity-7ebe2aeb1cbe` across every CLI process restart, provider swap (kimi → gemma-4-26b → glm-5.3-flash → kimi), and degraded-mode recovery. | `instance_name` in identity JSON is `"default"` even though the instance is `pinocchio-val`. |
| Episodic memory           | PASS   | `memory/state.db` `episodic` rows match each CLI turn; later turns cited prior boot/runtime-state content. | Two `agent.response` events per turn (`memory.episodic` and `runtime.cognition`). Spec asked for one. |
| Semantic memory           | PASS   | Facts table holds `project_codename=Blue Lantern`, `answer_style=terse`, `active_goal=finish pinocchio live validation`. New process **without** `--with-memory` answered "The validation project codename is Blue Lantern." | First "Remember that…" turn was classified `direct_response` and stored nothing. Fixed: `remember`/`memorize` now select ReAct. Rerun stored `NIGHTWATCH` via `memory` tool. |
| SelfState grounding       | PASS   | Unprompted, Jaeger reported `entity jaeger-entity-7ebe2aeb1cbe`, `current activity: processing_turn`, provider/model, and skill counts. That matches SelfState + config. | Activity is often stuck at `processing_turn` because each one-shot dies mid-turn from the reducer's point of view. |
| Provider independence     | PASS   | Identity unchanged across kimi / gemma-4-26b / glm-5.3-flash. Facts table unchanged. | gemma-4-26b returned empty text. glm-5.3-flash (the operator's live default) exhausted thinking on tool tasks. Provider swap preserves identity; it does not preserve competence. |
| Interface continuity      | FAIL   | Only the CLI one-shot path was a live pinocchio kernel. Operator Gateway :8810 has no event fabric. Isolated daemon did not speak Gateway/WebUI/Bridge. | No production proof that Gateway, Bridge, WebUI, and CLI share one EntityRuntime on a running product. Tool events use `session_id=dispatcher` while human messages use `cli`. |
| Direct response isolation | FAIL   | Math `17×9` → `153`, strategy `direct_response`, zero EffectLedger rows for that turn. | `direct_response` still exposes tools to the model and then allowlists them empty: "What are you working on?" produced four `unknown tool` calls (`board_view`, `memory`, `load_tools`). Conversational turns are marked `verification.completed` / `objective_unverified`. |
| ReAct execution           | PASS   | With `kimi-k2.7-code:cloud`, file write, delete, git commit, and memory writes dispatched real tools. Event order: `tool.proposed` → `authority.decision` → `tool.started` → `tool.completed`/`failed`. Independent disk/git confirmed. | `glm-5.3-flash:cloud` (live product model) on the same prompt: `thinking_exhausted`, file missing, no tool events. `write_file` rejects absolute paths, forcing terminal fallback. |
| Authority ordering        | PASS   | After fix: hook log max count per identical call = **1**. Denied `echo BLOCKED_PINOCCHIO_MARKER` never entered EffectLedger. Executor does not run. | **Before fix:** every permitted tool fired `pre_tool_call` twice (executor + `AuthorityLayer.default_shell_hooks_policy`). Live evidence: 19 invocations, 2× each tool. Denied path skipped `tool.proposed` because the first fire returned early. |
| Objective verification    | FAIL   | Contract exists and sometimes fail-closes (`unknown verify kind 'git_commit'`). Teleport was not marked verified. | Independent disk was wrong in both directions: file **existed** with correct bytes → `objective_failed` / `MissingPath`; successful delete → `objective_failed`; relative write → `objective_verified` as "Read-only operation". `tool success != objective verified` is true, but the verifier is not inspecting the real objective. |
| Deliberative search       | FAIL   | Executive selected `deliberate_planning` for the schema-migration prompt. Agent wrote a 3-approach plan and executed isolated scratch + git pull. Git log independently shows `f5d95a5 schema: migrate data.txt to v2`. | `plan.generated` event count = **0**. `cognition_provider` is not passed into `DeliberatePlanner` on the live path, so hardcoded template plans are the kernel's search. Model-authored plans happened *inside ReAct*, not as an independent critic-scored tree. |
| Self-Refine               | FAIL   | Casual chat did not obviously refine. High-consequence plan was a single ReAct trajectory. | No live critic cognition call, no revision call, no generate→critique→revise events. `SelfRefineEngine.default_critic` is a TODO/FIXME heuristic, not an LLM critic wired on the CLI path. |
| Reflexion                 | FAIL   | Tool failures exist (`write_file` absolute path, `execute_code` error `"None"`, `complete_task` ledger unfinished). | No structured reflection records with hypothesis / confidence / episode IDs / applicability. Failures do not change later planner input as Reflexion requires. |
| Sleep-time learning       | FAIL   | Production `--daemon` ran 75s (heartbeat interval configured at 1 minute). Event count 391 → 533. | Zero `system.heartbeat`, `memory.consolidated`, or sleep-time events. Daemon picked idle board cards (`benchmark_skill` loop) instead of consolidating. `SleepTimeProcessor` is not the daemon's idle work. |
| Skill acquisition         | FAIL   | Packaged skills load (105 recipes). | No candidate from live experience, no verification gate, no v3 package written into the instance skill dir (instance `skills/` count was 0 at boot). Production loader never registered a *learned* skill. |
| Passive perception        | FAIL   | `DesktopActivitySensor` exists. | Not started by `./jaeger` one-shot or `--daemon`. Zero `perception.sensed` events in 602-event log. `SensorSupervisor` is test-only. |
| Proactive wakeup          | FAIL   | Salience engine exists; quiet heartbeat code exists. | No live sensor→salience→cognition wake. Daemon did not emit heartbeat wakes. |
| Background continuity     | FAIL   | Daemon executed board/deep-think cards and recorded tool events into the same sqlite. | No operator-initiated durable task whose completion later appeared in another interface with provenance. Isolated harness had no second interface. |
| Crash recovery            | FAIL   | EffectLedger stored the successful `terminal` write (`status=done`) and would refuse silent replay of that key. Process restart preserved identity and memory. | Did not kill mid-side-effect. No live proof of `EffectIndeterminate` vs blind replay. One-shot processes never resume a run; they mint a new `turn-loop` commitment every launch (`commitments` table grows). |
| Idempotency               | FAIL   | Gateway `admit_request` has replay-by-`request_id`. | Not exercised on a live Gateway of this kernel. CLI one-shots send `request_id: null`. Duplicate CLI prompts re-execute. |
| Degraded-safe mode        | PASS   | Replaced `entity_events.sqlite3` with a directory. Mutating "Write a file…" → `DegradedRuntimeError: Sovereign EntityRuntime failed (unable to open database file). Mutating operations refused`. File absent. Chat "capital of France" → `Paris.` Identity intact. | Chat degraded path still boots the full tool catalog in the banner (`188 tools`) even though dispatch is allowlist-empty. |

---

## Phase notes (what actually happened)

### Phase 1 — Baseline boot

`./jaeger --instance pinocchio-val --no-warmup --no-cron --no-avatar --with-memory "Hello…"` started cleanly, resolved `ollama · glm-5.3-flash:cloud` then later kimi, loaded skills, minted identity, opened Event Fabric and `knowledge.sqlite3` under the isolated state root. No duplicate identity files. No sqlite inside the repo.

Operator fabric was already up (`Gateway PID 58893 :8810`, all-green health) and is a **different** process with no event DB.

### Phase 2 — Conversation

SelfState appeared in the model's answer (entity id, activity, model). One human message → one `human.message` event. Two `agent.response` events. "Remember that the validation project codename is Blue Lantern" produced fake `<memory_call>` XML and **no facts row**. Interfaces question hit `thinking_exhausted`.

### Phase 3 — Direct vs ReAct

| Prompt | Strategy | Tools | Independent check |
| :--- | :--- | :--- | :--- |
| `17 multiplied by 9? Do not use tools.` | `direct_response` | none | answer `153` |
| Create `pinocchio.txt` (glm-5.3-flash) | `react_loop` | none | **file missing**, `thinking_exhausted` |
| Same (kimi-k2.7-code) | `react_loop` | list/write/code/terminal | file on disk: `Pinocchio validation` |

Verifier said `objective_failed` / `MissingPath` on the successful kimi write.

### Phase 4 — Authority / safety

Permitted relative write created `sandbox/p4_ok.txt` containing `permitted`. Instrumented hook at `/tmp/jaeger-pinocchio-live-validation/pre_tool_hook.py`.

**Defect (fixed):** `HookedToolExecutor.execute` fired `shell_hooks.fire("pre_tool_call")` and then `AuthorityLayer.authorize` → `default_shell_hooks_policy` fired it again. Live counts were 2× per tool.

**Fix:** executor evaluates hooks only when the authority import path is unavailable. Canonical path is propose → authorize (hooks once) → start. Regression: `test_pre_tool_call_hook_fires_exactly_once`. Rerun: max per identical call = 1. Denied `echo BLOCKED_PINOCCHIO_MARKER` never landed in `effects`.

### Phase 5 — Objective verification

| Outcome | Agent claim | Independent | Verifier event |
| :--- | :--- | :--- | :--- |
| File write | created | file present | `objective_failed` |
| File delete | deleted | `p4_ok.txt` gone | `objective_failed` |
| Git commit | committed | `b8af66a pinocchio-git-validation`, `data.txt=v2` | `complete_task` fail-closed on `git_commit` |
| Unknown (teleport mug) | refused | no fake success | `objective_unverified` |
| Process start/stop | not run | — | — |

`tool success != objective verified` holds. Ground-truth matching does not.

### Phase 6 — Persistent memory

After wording the request as **Write** (so Executive chose ReAct), facts survived a full process exit. Recall without transcript injection (`JAEGER_WITH_MEMORY` unset) still returned Blue Lantern.

Temporary "oat latte" was written into `facts` with tags `temporary,today`. It was promoted to semantic memory anyway.

`remember` verb now maps to ReAct (`executive.py` ACTION_HINTS). Rerun stored `NIGHTWATCH`.

### Phase 7 — Provider swap

Identity continuous. Memory table continuous. Answers after swap were weak or empty depending on model. The kernel is provider-independent; the *agent's usefulness* is not.

### Phase 8 — Interface swap

Not demonstrated. CLI only on the pinocchio kernel.

### Phase 9 — Deliberative search

Executive: `deliberate_planning`. Git independently gained `f5d95a5 schema: migrate data.txt to v2` after isolated scratch clone + pull. Kernel did not emit `plan.generated`, did not record ≥3 critic-scored model candidates, and does not pass a live `cognition_provider` into `DeliberatePlanner` (hardcoded three templates remain the fallback).

### Phases 10–15, 17–20

Not demonstrated on production entrypoints, except: daemon generated lots of tool events (idle board), not sleep-time consolidation; crash/idempotency/adversarial suites were not fully driven. Degraded mode (Phase 16) **was** demonstrated, above.

---

## Fixes landed during this audit

Only live failures that blocked the architecture, with regression tests:

1. **Duplicate `pre_tool_call`** — `packages/jaeger-agent/jaeger_agent/tool_executor.py`  
   Hooks run once, in `AuthorityLayer`.  
   Tests: `test_pre_tool_call_hook_fires_exactly_once`, `test_hooked_executor_blocks_the_call`.

2. **`Remember that…` classified as chat** — `jaeger_ai/core/entity/executive.py`  
   `remember` / `memorize` select `REACT_LOOP`.  
   Test: `test_audit_4_executive_strategy_selection`.

`25 passed` in those suites.

---

## Remaining production defects (do not treat as done)

1. Direct-response still advertises tools, then fails them as `unknown tool`.
2. Objective verifier does not look at the real filesystem/git state for the stated objective.
3. Two `agent.response` events per turn.
4. Sleep-time / heartbeat / sensors are not on the daemon/CLI idle path.
5. Deliberate search, Self-Refine, Reflexion, and Voyager skill promotion are not live cognition modes.
6. Operator Gateway process currently running has no Event Fabric.
7. `write_file` rejects absolute paths the model naturally emits; terminal then mutates anyway.
8. Temporary facts are stored as semantic `facts`.
9. One-shot CLI mints a new turn-loop commitment every process; runs do not resume.
10. Product-default cloud model (`glm-5.3-flash:cloud`) cannot complete a ReAct file write.

---

## Final acceptance

Jaeger on `pinocchio`, launched as a real product CLI, **does**:

- keep one `entity_id` across process death and model swap
- persist episodic + semantic memory in SQLite, retrievable without stuffing the transcript
- expose SelfState to the model
- choose Direct vs ReAct at the executive
- run propose → authorize → tool → consequence events
- refuse mutations when the event kernel cannot open
- write and delete files and make git commits that independent inspection confirms (with a tool-capable model)

It **does not** yet demonstrate, as one long-lived product:

- strategy-faithful cognition modes (LATS / Self-Refine / Reflexion / sleep / skill learning)
- objective verification that matches the world
- proactive sensing
- multi-interface identity
- crash-safe resume
- Gateway idempotency
- the operator's already-running fabric behaving as this architecture

**Round 1 verdict (historical, 2026-09-21 morning):** The actual running agent is closer to a persistent ReAct daily-driver with a new event kernel beside it than to the full Universal Persistent Agent Architecture operating as one organism.

---

# Round 2 — production wiring (2026-09-21 evening)

Isolated instance unchanged: `entity_id=jaeger-entity-7ebe2aeb1cbe`, `pinocchio-val`, provider `kimi-k2.7-code:cloud`. Regression: 55 unit tests passed (`test_upaa_live_correctness`, pinocchio entity, production runtime, shell hooks, executive).

## Capability history

### Direct response isolation

**BEFORE:** `DIRECT_RESPONSE` still advertised the full tool catalog; the model emitted `board_view` / `memory` / `load_tools` which failed as `unknown tool`.

**FIX:** `_run_direct_model_runner` builds a throwaway `JaegerAgent(tools=[])` so the provider schema is empty, plus a prose retry if a tool-shaped blob still appears. `tool_allowlist([])` remains as the dispatch backstop.

**AFTER:** Live CLI `"What are you working on right now?"` → `executive.decision` `direct_response`, one `agent.response` (`"I'm answering your question right now."`), zero `unknown tool` strings, `verification` `objective_unverified`.

**EVIDENCE:** events 603–607 in isolated `entity_events.sqlite3`. Test `test_direct_response_exposes_zero_tools`.

### Objective verification

**BEFORE:** successful writes/deletes marked `objective_failed` / `MissingPath` because verification used the last display string (`complete_task(... Wrote ...)`) and queried the *oldest* 160 events.

**FIX:** `derive_verification_action` reconstructs write/delete/git from `tool.started`+`tool.completed` (merged by `call_id`) and from absolute paths in the objective. `execute_turn` queries `since_ts` + event types, not `ORDER BY id ASC LIMIT`. Absolute objective paths win over relative `workspace/...` cwd guesses.

**AFTER:** Live write of `p0b_write6.txt` with content `verified-ok` → disk match → `verification.completed` `objective_verified` / `file_write_verifier`. One `agent.response`.

**EVIDENCE:** `DISK:[verified-ok]` and event payload `Verified file write at /private/tmp/.../p0b_write6.txt`. Tests `test_derive_file_write_from_terminal_and_disk`, `test_derive_file_delete`, `test_derive_git_commit`, `test_execute_turn_verifies_write_from_tool_events`.

Delete/git live reruns were not repeated this round; unit probes cover those verifiers independently.

### Duplicate `agent.response`

**BEFORE:** `memory.episodic.record_interaction` wrote one `agent.response`; `EntityRuntime.record_agent_response` wrote a second.

**FIX:** `record_interaction` no longer appends to the event fabric. Canonical writer is `record_agent_response`, payload includes `user_text` + `agent_response`. Episode projection reads that single event.

**AFTER:** Direct and ReAct live turns emit exactly one `agent.response`.

**EVIDENCE:** `agent.response count 1` on P0-A and P0-B live turns. Test `test_single_agent_response_event`.

### Deliberative search

**BEFORE:** `plan.generated` count = 0; hardcoded templates; regex-only trigger.

**FIX:** `score_task_complexity` (verbs, comparison language, destructive scope, length, reflections, goals). Threshold + `compare_plans` selects `DELIBERATE_PLANNING`. `cognition_provider` is the live `model_runner`. Router emits `plan.generated` (candidate list), `plan.criticized`, `plan.selected`, `plan.replanned`.

**AFTER:** Isolated daemon produced `plan.generated` events 909–910 with three named candidates (`Conservative playbook edit`, `New reusable tool-guard skill`, `Baseline-only no-op plan`) — model-generated, not the fallback template names.

**EVIDENCE:** sqlite rows 909–910. Test `test_complexity_score_selects_deliberate`. A dedicated CLI "compare approaches" live turn was not re-run this evening after the write-verification loop.

### Self-Refine

**BEFORE:** unreachable on CLI.

**FIX:** `ExecutiveDecision.refinement_required` for deployment/architecture/security artifacts. `execute_turn` runs `SelfRefineEngine.refine_artifact` and emits `artifact.generated/critiqued/revised/validated`.

**AFTER:** Wired. No live high-consequence artifact turn was executed in round 2.

**EVIDENCE:** code path in `runtime.py`; no live `artifact.*` rows yet.

### Reflexion

**BEFORE:** failures stored loosely; no retrieval events.

**FIX:** `execute_turn` retrieves applicable reflections before strategy selection and emits `reflection.retrieved`. Learning emits `reflection.created` on `OBJECTIVE_FAILED`.

**AFTER:** 2 `reflection.created` events in the isolated log (from earlier failed complete_task/verification loops). Retrieval-changes-future-plan live sequence not re-proven.

**EVIDENCE:** `reflection.created` count = 2.

### Heartbeat / sensors / sleep-time / resident

**BEFORE:** `--daemon` for 75s emitted zero heartbeat, sleep, or perception events; board work starved heartbeat.

**FIX:** Exclusive `entity.resident.lock`. Gateway and daemon `try_become_resident`. Quiet `system.heartbeat` is emitted when due *even if* the board has work. Sensors start from resident daemon/gateway when `sensors.desktop.enabled`. Sleep-time runs on quiet idle. `JAEGER_HEARTBEAT_DUE=1` for tests.

**AFTER:** Isolated daemon: `system.heartbeat` = 1 (payload `quiet: false` because board work existed); `perception.sensed` = 42 (frontmost app redacted to names, idle seconds, disk); `sleep_time.started` = 0 (idle was not quiet). Operator Gateway `:8810` was not restarted onto this kernel.

**EVIDENCE:** events 877 (heartbeat), 927–928 (perception). Daemon log: `entity jaeger-entity-7ebe2aeb1cbe`.

### Provider routing

**BEFORE:** `glm-5.3-flash:cloud` remained the default ReAct engine despite `thinking_exhausted`.

**FIX:** `model_capabilities.py` seeds kimi `react: PASS`, glm-5.3-flash `react: FAIL`. `ensure_role_client` reroutes ReAct away from FAIL unless `JAEGER_FORCE_MODEL=1`. Emits `provider.rejected` / `provider.selected`.

**AFTER:** Isolated instance already on kimi. Operator default glm was not live-rerouted (operator fabric not restarted).

**EVIDENCE:** `DEFAULT_CAPABILITIES` + `ensure_role_client` in `_run_turn`.

### Skill acquisition / crash / idempotency / Gateway+WebUI+CLI identity

**BEFORE:** FAIL (round 1).

**FIX (partial):** Sleep-time skill review can promote a playbook into `skills_dir` after ≥2 successful `write_file`/`terminal`/`memory` tools. Gateway `/health` now includes `entity_id`. CLI and Gateway share `operator_state_root()` sqlite when `JAEGER_STATE_DIR` matches.

**AFTER:** Not live-validated. Operator Gateway still has no `~/.jaeger/entity_events.sqlite3`. Crash-kill mid-effect and duplicate Gateway `request_id` not rerun.

**EVIDENCE:** code only.

---

## Round 2 scorecard

| Capability | Round 1 | Round 2 | Notes |
| :--- | :--- | :--- | :--- |
| Identity continuity | PASS | PASS | Unchanged `jaeger-entity-7ebe2aeb1cbe` |
| Episodic memory | PASS | PASS | Single autobiographical `agent.response` |
| Semantic memory | PASS | PASS | Preserved |
| SelfState grounding | PASS | PASS | Preserved |
| Provider independence | PASS | PASS | Capability router added; glm still FAIL for ReAct |
| Interface continuity | FAIL | FAIL | Isolated CLI+daemon share fabric; operator Gateway not on this kernel |
| Direct response isolation | FAIL | PASS | Empty tool schema; live one-sentence reply, no unknown-tool |
| ReAct execution | PASS | PASS | Preserved (kimi) |
| Authority ordering | PASS | PASS | Preserved (single hook fire) |
| Objective verification | FAIL | PASS | Live write `p0b_write6.txt` → `objective_verified`; disk matched |
| Deliberative search | FAIL | PASS* | `plan.generated` with 3 named candidates on daemon; CLI compare-plans not re-run |
| Self-Refine | FAIL | FAIL | Wired, no live artifact turn |
| Reflexion | FAIL | FAIL | `reflection.created` exists; retrieval→plan-change not proven |
| Sleep-time learning | FAIL | FAIL | Heartbeat yes; `sleep_time.started` still 0 (board not quiet) |
| Skill acquisition | FAIL | FAIL | Promoter writes playbooks; no live reuse proof |
| Passive perception | FAIL | PASS | 42 `perception.sensed` on isolated daemon with sensors enabled |
| Proactive wakeup | FAIL | FAIL | Tier-0 telemetry only; no salience→cognition wake demonstrated |
| Background continuity | FAIL | FAIL | Daemon did board/deep-think; no cross-interface completion |
| Crash recovery | FAIL | FAIL | Not rerun |
| Idempotency | FAIL | FAIL | Not rerun |
| Degraded-safe mode | PASS | PASS | Not regressed |

\* Deliberative search: event fabric now records model-generated plans. Independent critic-scored tree vs fallback templates still depends on `cognition_provider` returning parseable JSON.

---

## OVERALL VERDICT

**C. LIVE VALIDATED WITH LIMITATIONS**

P0 live defects that blocked the architecture (tool leakage on chat, wrong objective status, duplicate autobiographical events) are fixed and re-observed on `./jaeger --instance pinocchio-val`. The isolated daemon now emits `system.heartbeat` and `perception.sensed` from the resident lock holder.

Not merge-ready (not D): operator Gateway/WebUI/Bridge still a separate world until that process is restarted onto this kernel; sleep-time, Self-Refine, Reflexion-guided replanning, learned-skill reuse, crash resume, and Gateway `request_id` idempotency remain unproven on a single resident product.

Do not merge into master.

---

## Round 3 — operator Pinocchio kernel and remaining live gates

**Date:** 2026-09-21  
**Branch:** `pinocchio` (not merged to master)  
**Identities (do not conflate):**

| World | `entity_id` | State root | Event DB | Role |
| :--- | :--- | :--- | :--- | :--- |
| Isolated harness `pinocchio-val` | `jaeger-entity-7ebe2aeb1cbe` | `/tmp/jaeger-pinocchio-live-validation/state` | 1462 events in `entity_events.sqlite3` | Round 1–2 kernel proofs + Round 3 sleep / Reflexion / Self-Refine / skills / crash attempt |
| Operator daily driver `jaeger` | `jaeger-entity-7615957f0fa6` | `~/.jaeger` | 184 events in `~/.jaeger/entity_events.sqlite3` | Restarted Gateway / WebUI / Bridge / CLI attach |

Round 1 recorded that the already-running operator fabric had **no** event DB. That remains true **as of that restart**. Round 3 restarted the operator stack from this checkout; the operator identity did **not** become `7ebe2aeb1cbe`.

### Operator stack after `./jaeger restart --no-app --no-containers`

| Item | Value |
| :--- | :--- |
| Gateway | PID **62387**, started 2026-09-21 01:13:17, `python -u -B -m jaeger_ai.core.gateway.server`, `source_file` = pinocchio `jaeger_ai/core/gateway/server.py` |
| Bridge | PID **62396**, `:8791/health` ok, instance `jaeger` |
| WebUI | PID **62499**, `:8790` HTTP 200 |
| WebUI adapter | PID **62492**, `:8791` |
| Native MCP HTTP | PID **62453**, `:8792/mcp` |
| State root | `/Users/matthewjenkins/.jaeger` |
| Event DB | `~/.jaeger/entity_events.sqlite3` (created by this kernel) |
| Identity file | `~/.jaeger/entity_identity.json` → `jaeger-entity-7615957f0fa6` |
| Gateway `/health` | `status=ok`, `entity_id=jaeger-entity-7615957f0fa6`, `entity_resident=true` |
| Launchd | `com.jenkinsrobotics.jaeger-gateway` / `-bridge` / `-mcp-http` / WebUI |

CLI one-shots against the locked instance attach through Gateway (`/v1/sessions/cli:jaeger/turns`) rather than minting a second entity.

---

### 1. Operator Gateway / WebUI / Bridge on the Pinocchio kernel

**ROUND 2:** FAIL — operator Gateway `:8810` had no Event Fabric; isolated CLI+daemon only.

**ROUND 3:** PASS — operator process tree is this checkout; Event Fabric exists; all three UIs share `jaeger-entity-7615957f0fa6`.

**RESULT:** PASS

**EVIDENCE:** health `source_file` pinocchio tree; sqlite event ids 1–184; CLI attach, WebUI `:8790/v1/sessions`, Gateway turns all write `human.message` into the same DB.

**DEFECT FOUND:** First CLI remember (events 1 + 5) duplicated `human.message` (`cli:jaeger` gateway + `dispatcher`) because MCP `_bridge_chat` dropped `is_subordinate`.

**FIX:** Pass `is_subordinate` MCP → `bridge_client` → bridge worker → `run_for_voice`. Locked CLI forwards to Gateway instead of a second runtime.

**RETEST:** After restart, LYRE remember = one human (id 83) + one `agent.response` (id 91). WebUI LYRE recall = one human (id 92) + one response (id 100, text `LYRE`).

---

### 2. Real multi-interface continuity

**ROUND 2:** FAIL — no shared operator kernel.

**ROUND 3:** PASS on the operator identity (not pinocchio-val).

**RESULT:** PASS

**EVIDENCE:**

* CLI/Gateway: “Remember that Round Three codename is ORPHEUS.” → fact `round_three_codename=ORPHEUS` (2026-09-21T08:11:50Z).
* WebUI session `551d09d936754e5b812e7f937ed2c1da`: “What is the Round Three codename?” → agent.response id 29 `ORPHEUS`.
* Gateway session `d96059b66d03425482421e45ff32f534`: “Continue the Round Three validation…” → recalled ORPHEUS from the store.
* Follow-up token LYRE stored via `cli:jaeger` request `r3-lyre-001`; WebUI session `33d475fe2103480d906892998680366a` answered `LYRE`.
* Same `entity_id`, same `~/.jaeger/entity_events.sqlite3`, same `instances/jaeger/memory/state.db` facts.

**DEFECT FOUND:** Pre-fix duplicate human on the first remember. After fix, one human event per actual message on WebUI and subsequent Gateway turns.

**FIX:** `is_subordinate` + Gateway attach (above).

**RETEST:** LYRE path: 1 human / 1 response. No transcript-only trick: `memory` tool `remembered: true` and facts table row.

---

### 3. Sleep-time must fire for real

**ROUND 2:** FAIL — heartbeat yes; `sleep_time.started` = 0 because the board was not quiet.

**ROUND 3:** PASS on isolated daemon. Sleep ran without calling `SleepTimeProcessor` from the test harness.

**RESULT:** PASS

**EVIDENCE:**

* Cycle 1 (events 971–974): `system.heartbeat` quiet=true → `sleep_time.started` → `memory.consolidated` (claims_recorded=8, skills_promoted=0) → `sleep_time.completed`.
* Cycle 2 (events 1237–1247) after moving heartbeat/sleep **before** skill-review sweep: quiet=true, `claims_recorded=84`, `reflections_generated=1`, `skills_promoted=3`, jobs `[consolidation, reflection, skill_candidate_review]`.
* Durable packages survived process kill: `state/skills/learned_{write_file,terminal,memory}/SKILL.md` + `manifest.yaml`.

**DEFECT FOUND:** Daemon `skill_review.sweep` queued ready cards *before* heartbeat, so sleep never saw a quiet board.

**FIX:** Resident loop runs heartbeat + sleep-time first; skill-review sweep after. Sleep quiet = no `ready`/`in_progress` (backlog no longer blocks). `query_events(since_ts=now-86400)` so skill review sees recent `tool.completed` rows.

**RETEST:** Event 1237 quiet heartbeat immediately followed by skill.candidate/promoted and sleep_time.completed.

---

### 4. Live Reflexion reuse

**ROUND 2:** FAIL — `reflection.created` existed; retrieval→plan-change not proven.

**ROUND 3:** PARTIAL — live retrieve + cognition inject; first-action change is inconsistent.

**RESULT:** PARTIAL

**EVIDENCE:**

* Controlled missing-file failure: `tool.failed` `read_file` / `not found` → `verification.completed` `objective_failed` (tool_failure_override) → `reflection.created` with supporting episode ids.
* After formulate fix, new records use applicability `["read_file","filesystem","file_io","not_found"]` (e.g. `refl-1789979758299`).
* Similar task “Use the read_file tool to open …/orpheus-missing-clean2.txt”: `reflection.retrieved` id 1019 (`count=1`, ids `[refl-1789979758299]`) **before** tools.
* Unit: ReAct prompt contains `# Retrieved Failure Hypotheses`; planner alias `get_relevant_reflections` == `retrieve_applicable`.
* One similar turn (1004) listed the directory after the failed read. The clean2 turn still issued `read_file` first, then stopped.

**DEFECT FOUND:** Planner called missing `get_relevant_reflections` (swallowed). Formulate used human payload tool=`action`. Retrieval on “action” applicability missed clean `read_file` prompts.

**FIX:** Alias `get_relevant_reflections`. Extract tool name from objective/evidence. ReActHandler prepends `to_prompt_context_block`. Tool-failure override evidence includes `(read_file)`.

**RETEST:** retrieve event 1019 live; strategy-change gate not clean enough for D.

---

### 5. Live Self-Refine

**ROUND 2:** FAIL — wired, no live artifact turn.

**ROUND 3:** PASS on isolated CLI.

**RESULT:** PASS

**EVIDENCE:** Prompt “Create a deployment plan for this dummy service including rollback, verification, and failure recovery.”

* `executive.decision` react_loop (artifact hints matched).
* `artifact.generated` id 1076, 9712 chars.
* `artifact.critiqued` id 1077, `iterations=2`, `critic=provider` (model critic actually called).
* `artifact.revised` id 1078, 7787 chars — draft dummy file-copy plan vs revised Order Service v2.3.1 K8s/canary/rollback plan.
* `artifact.validated` id 1079.
* Routine chat “What is 17 multiplied by 9? Do not use tools.” → `direct_response`, **zero** artifact.* events (1083–1088).

**DEFECT FOUND:** First live refine (event 993) emitted only `artifact.generated` (258 chars) then the 300s CLI timeout killed the critic.

**FIX:** If the ReAct reply is under 400 chars, `cognition_provider` drafts the artifact before critique. Critic/reviser are the live `model_runner`.

**RETEST:** Full generate→critique→revise→validate chain above; math control has no refine.

---

### 6. Live skill acquisition and reuse after restart

**ROUND 2:** FAIL — promoter could write playbooks; no live reuse.

**ROUND 3:** PASS on isolated daemon + post-restart CLI.

**RESULT:** PASS

**EVIDENCE:**

* Sleep cycle 1240–1245: `skill.candidate` → verify → `skill.promoted` for `learned_terminal` (30×), `learned_write_file` (9×), `learned_memory` (10×).
* Disk v3 packages under `state/skills/learned_write_file/` (SKILL.md, manifest.yaml, run.py, tests/smoke_test.py).
* Full process kill; new CLI: “Write a one-line file at sandbox/r3_skill_reuse.txt containing the word SKILL-OK.”
* `skill.used` id 1258 `learned_write_file` **before** `executive.decision`; then `write_file` ran; file `skills/sandbox/r3_skill_reuse.txt` = `SKILL-OK`.
* Pipeline `_load_from_disk` so restart registry is not empty.

**DEFECT FOUND:** `SKILL_USED` was defined and never emitted. In-memory `_promoted_skills` died on restart even when files existed. Sleep queried oldest rows.

**FIX:** Load packages on init; `matching_skills`; emit `skill.used` and inject playbook into ReAct prompt; recent `since_ts` queries.

**RETEST:** Events 1240–1245 and 1258; file on disk after restart.

---

### 7. Crash-resume

**ROUND 2:** FAIL — not rerun.

**ROUND 3:** FAIL — identity survived; mid-effect kill of A-before-B/C was not recovered as a resumed run.

**RESULT:** FAIL

**EVIDENCE:** Multi-step crash2 completed A+B+C in one process (`r3_crash2_*.txt` on disk). Crash3 SIGKILL during early tools left **no** `r3_crash3_A.txt` and **no** `agent.response` for human 1426. Restarted one-shots mint a new run id (`_open_or_create_run` → `new_id()`). `LedgerToolExecutor` only wraps `side_effect="external"`; `write_file` default `side_effect=""`.

**DEFECT FOUND:** Crash resume of the *same* run is not on the CLI one-shot path. File writes are not EffectLedger keys.

**FIX:** None in this round (would be run-store recovery + authoritative mutating tools). Not an architecture rewrite for an unproven gate.

**RETEST:** Not passed. Identity `jaeger-entity-7ebe2aeb1cbe` still stable.

---

### 8. Gateway request-id idempotency

**ROUND 2:** FAIL — not exercised on this kernel.

**ROUND 3:** PARTIAL — replay does not re-execute; Gateway marks native turns `failed` even when the file is written.

**RESULT:** PARTIAL

**EVIDENCE:**

* Request X `r3-idemp-X-015022`: one `human.message` id 101, file `workspace/round3_idemp2.txt` = `ORPHEUS-X`.
* Identical POST with same `request_id`: `replayed: true`, same `turn_id`, mtime unchanged.
* Same text, different id `r3-idemp-Y-015022`: new human id 127, treated as a new request; agent read-back, no rewrite.
* Earlier ORPHEUS-IDEMP: replay X `replayed True`; Y new human 69.

**DEFECT FOUND:** Native receipt `halt_reason=complete_task` is stored as Gateway `status=failed` (“Native agent did not return a confirmed result”) even when tools succeeded.

**FIX:** `admit_request` replay-by-id already correct. No status-mapping change in this round (would touch Gateway completion semantics).

**RETEST:** Replay X does not duplicate the human event or the file write.

---

### 9. Background continuity

**ROUND 2:** FAIL — no cross-interface completion.

**ROUND 3:** PARTIAL — Gateway turn completed in the shared fabric and was recalled from a second session; `background.completed` event count = 0.

**RESULT:** PARTIAL

**EVIDENCE:** POST `/v1/sessions/r3-bg-015627/turns` returned immediately (`status=running`). File `workspace/round3_bg.txt` = `BACKGROUND_ORPHEUS`. Later session `r3-bg-ask-015657` answered from persistent state: “workspace/round3_bg.txt contains BACKGROUND_ORPHEUS.” Both sessions share operator sqlite (humans 141 and 167). Gateway `/health` `background_delivery.received=0` (outbox path unused).

**DEFECT FOUND:** Async Gateway turns do not emit `background.completed`. Request status still `failed` after success.

**FIX:** None beyond existing Event Fabric writes of the turn itself.

**RETEST:** Second interface retrieved the file contents from durable state.

---

### 10. Long-run resident snapshot

Isolated daemon + CLI mixed workload on `jaeger-entity-7ebe2aeb1cbe` (1462 events):

| Metric | Count |
| :--- | :--- |
| Total events | 1462 |
| `human.message` | 51 |
| Duplicate human texts (extra copies) | 15, mostly Deep Think / repeated write/read probes |
| `agent.response` | 70 (includes daemon cards; CLI turns 1 canonical response) |
| `perception.sensed` | 98 |
| `system.heartbeat` | 6 |
| Cognition wakes (`executive.decision`) | 54 |
| `sleep_time.*` | 2 started / 2 completed |
| `reflection.created` / `retrieved` | 8 / 9 |
| `skill.candidate` / `promoted` / `used` | 3 / 3 / 7 |
| Verification | verified 8, failed 10, unverified 29 |
| `provider.selected` / `rejected` | operator: 1 / 1 (glm ReAct FAIL → kimi) |
| Active Deep Think cards after pause | forced `done` for sleep; sweep can requeue |
| Unresolved crash3 turn | human 1426, no `agent.response` |

Operator fabric on `jaeger-entity-7615957f0fa6`: 184 events, 12 humans, 6 `agent.response` (several Gateway turns stored `status=failed` despite tool success). `provider.rejected` glm, `provider.selected` kimi. Facts: `round_three_codename=ORPHEUS`, `round_three_operator_token=LYRE`.

Passive perception, heartbeat, sleep-time, reflection, skill events, interface switch (CLI/WebUI/Gateway), provider reject, and controlled missing-file failure all occurred on the Pinocchio kernel. Proactive salience→cognition wake remains Round 2 FAIL (not re-proven as a distinct wake).

---

## Round 3 scorecard

| Capability | Round 2 | Round 3 | Notes |
| :--- | :--- | :--- | :--- |
| Identity continuity | PASS | PASS | Isolated `7ebe2aeb1cbe`; operator `7615957f0fa6` documented separately |
| Episodic / semantic / SelfState | PASS | PASS | ORPHEUS/LYRE facts; no isolated identity drift |
| Provider independence | PASS | PASS | glm still FAIL for ReAct; `provider.rejected` on operator |
| Interface continuity | FAIL | PASS | Operator Gateway/WebUI/Bridge/CLI share Pinocchio fabric |
| Direct response isolation | PASS | PASS | Math 153, empty tools, no artifact.* |
| ReAct / authority / verification | PASS | PASS | Missing-file → `objective_failed`; writes verified on disk |
| Deliberative search | PASS* | PASS* | Live `plan.generated` on daemon skill-review |
| Self-Refine | FAIL | PASS | generated→critiqued→revised→validated, critic=provider |
| Reflexion | FAIL | PARTIAL | retrieved + prompt inject; first-tool change inconsistent |
| Sleep-time learning | FAIL | PASS | Two real daemon cycles; second promoted 3 skills |
| Skill acquisition | FAIL | PASS | candidate→promoted→`skill.used` after restart |
| Passive perception | PASS | PASS | 98 `perception.sensed` |
| Proactive wakeup | FAIL | FAIL | Not a distinct salience→cognition wake |
| Background continuity | FAIL | PARTIAL | Cross-session recall; no `background.completed` |
| Crash recovery | FAIL | FAIL | Same-run resume not live |
| Idempotency | FAIL | PARTIAL | Replay skips work; Gateway status `failed` |
| Degraded-safe mode | PASS | PASS | Not regressed |

---

## Round 3 tests

After production fixes:

* `dev/tests/test_upaa_live_correctness.py` — formulate extracts `read_file`; `get_relevant_reflections` alias; skill disk reload + `skill.used`; ReAct prompt contains retrieved hypotheses.
* `dev/tests/test_upaa_closure_pass.py::test_closure_skill_promotion_and_restart_discovery` — restart `get_skill` from disk.
* Ran: `test_upaa_production_runtime.py` (9), `test_upaa_closure_pass.py` (8), `test_upaa_live_correctness.py` (13) → **30 passed**; `test_pinocchio_entity.py` → **12 passed**. Suite isolation plugin flagged live operator files mutated by this campaign (`round3_bg.txt`, git objects), not by the tests themselves.

---

## ROUND 3 OVERALL VERDICT

**C. LIVE VALIDATED WITH LIMITATIONS**

Operator Gateway/WebUI/Bridge now run the Pinocchio kernel (separate identity from `pinocchio-val`). Multi-interface continuity, automatic sleep-time, live Self-Refine, and learned-skill reuse after restart are live-proven. Reflexion retrieval is live; strategy change is not clean. Gateway `request_id` replay works; completion status is wrong. Background results are retrievable from the same fabric without `background.completed`. Crash-resume of a killed mid-effect run is not live-proven.

D. LIVE VALIDATED FOR PINOCCHIO MERGE is **not** justified.

Do not merge into master.

---

## Operational OS implementation (post Round 3)

Authoritative spec: JAEGER PRODUCTION OS IMPLEMENTATION SPECIFICATION. Readiness write-up: `docs/architecture/JAEGER_OPERATIONAL_READINESS.md`.

Round 3 FAIL/PARTIAL items are **not** silently closed. Code now contains:

| Spec item | Implementation | Live retest |
| :--- | :--- | :--- |
| Instance-scoped fabric | `InstanceLayout.memory_dir` event store + identity; legacy `~/.jaeger/entity_*` migrated on OWNER boot | pending resident restart |
| One OWNER | `EntityRuntimeMode.OWNER` (Gateway) / `ATTACHED_CLIENT` / `TEST` | pending |
| `jaeger start` READY gate | waits `GET /v1/runtime/status` ready | pending |
| Gateway terminal `completed` | `native_turns._terminal_status` treats `complete_task`+text as completed | unit PASS; live pending restart |
| `background.completed` payload | task_id, source_session, originating_event_id, status, result_summary, artifact_refs | unit PASS |
| Reflexion first-action constraint | `to_planning_constraints` AVOID first tool | unit PASS; live first-action pending |
| Crash resume scan | `RecoveryManager.scan_resumable_runs` on OWNER boot; pending effects not auto-retried | scan wired; SIGKILL resume still Round 3 FAIL until proven |
| Indexing | `IndexCoordinator` hash skip + FTS | unit PASS |
| Maintenance worktree | `MaintenanceCoordinator` isolated branch, protected paths, dry-run candidate | unit PASS |

Do not treat unit PASS as live PASS.
