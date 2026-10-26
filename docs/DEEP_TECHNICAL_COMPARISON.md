# Deep Technical Comparison: JaegerAI vs Hermes Agent vs OpenClaw
## Agentic Framework Architecture & Proactive Intelligence

**Assessment Date:** 2026-10-25
**Focus:** Agent loops, proactive intelligence, memory architecture, autonomous behavior

---

## Executive Summary

| Aspect | JaegerAI | Hermes Agent | OpenClaw |
|--------|----------|--------------|----------|
| **Agent Loop** | Event-sourced EntityRuntime + subordinate ReAct | Phase-decomposed ReAct with 25+ turn handlers | Tool-loop with abort signals |
| **Proactive Intelligence** | ✅ **Superior** — Native sensors, heartbeat, initiative, salience | ⚠️ Cron-driven, `/loop` command | ⚠️ Cron jobs, heartbeat (deprecated→migrated to cron) |
| **World Model** | ✅ **Native** — SemanticMemory + WorldStore with epistemic layers | ❌ No persistent world model | ⚠️ Memory files only |
| **Event Sourcing** | ✅ **Native** — 40+ event types, append-only SQLite | ⚠️ SQLite sessions (not event-sourced) | ⚠️ SQLite + JSONL transcripts |
| **State Management** | ✅ **Deterministic** — Pure reducers, replay from events | ⚠️ Mutable state objects | ⚠️ Mutable agent state |
| **Memory Taxonomy** | **5-class** (Working/Episodic/Semantic/Reflective/Procedural) | 2-layer (curated files + FTS5 sessions) | 2-layer (files + dreaming) |
| **Verification** | ✅ **Independent probes** — Disk/git/process verification | ⚠️ Tool return strings | ⚠️ Tool return strings |
| **Trust Model** | ✅ **Zero trust** — PolicyKernel, approval gates | ⚠️ Approval modes | ⚠️ Approval + sandbox |
| **Multi-Agent** | ✅ **Native** — Roundtable debate, Dispatcher, delegation | ⚠️ Subagents, kanban, `/loop` | ✅ Worktrees, tasks, agents |
| **Simulation-First** | ✅ **Native** — Propose → simulate → verify → approve → act | ❌ | ❌ |

**Verdict:** JaegerAI has a **fundamentally more sophisticated agentic architecture** — it's an **event-sourced persistent entity** with proactive intelligence built into the core, not bolted on via cron jobs.

---

## 1. Agent Loop Architecture

### 1.1 JaegerAI: Event-Sourced EntityRuntime

**Philosophy:** "State is reconstructed by replaying events through pure reducer functions. Models reason ABOUT state; they don't authoritatively write it."

```python
# jaeger_ai/core/entity/runtime.py
class EntityRuntime:
    def ingest(self, event: JaegerEvent) -> tuple[SelfState, AttentionDecision]:
        """Core Invariant Execution Loop.
        
        1. PERSIST event durably to event store (crash-safe)
        2. UPDATE SelfState deterministically via REDUCER (pure function)
        3. EVALUATE Attention/Salience (tiered classifier)
        4. WAKE cognition if required (CognitionRouter dispatch)
        """
        # 1. Persist with idempotency (SHA256 of content)
        persisted = self.event_store.append(event)
        is_duplicate = (persisted.event_id != event.event_id)
        
        # 2. Deterministic state reduction — PURE FUNCTION, no side effects
        with self._state_lock:
            if not is_duplicate:
                self._state = reduce_event(self._state, persisted)
            current_state = self._state
        
        # 3. Attention/Salience evaluation
        decision = self.salience_engine.evaluate(persisted, current_state)
        
        # 4. Wake cognition if salient
        if decision.wake_cognition and not is_duplicate:
            for handler in self._cognition_handlers:
                handler(persisted, current_state)
        
        return current_state, decision

    def reboot(self) -> None:
        """Cold boot: replay ALL events to reconstruct state."""
        base_state = SelfState(identity=self.identity, boot_timestamp=time.time())
        self._state = replay_events(base_state, self.event_store.replay_all())
```

**40+ Event Types** (immutable, append-only):
```python
class EventType(str, Enum):
    # Human interaction
    HUMAN_MESSAGE = "human.message"
    # System events
    SYSTEM_HEARTBEAT = "system.heartbeat"
    SYSTEM_OBSERVATION = "system.observation"
    # Executive decisions
    EXECUTIVE_DECISION = "executive.decision"
    # Tool lifecycle
    TOOL_PROPOSED = "tool.proposed"
    AUTHORITY_DECISION = "authority.decision"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    VERIFICATION_COMPLETED = "verification.completed"
    # Learning
    LEARNING_UPDATED = "learning.updated"
    MEMORY_CONSOLIDATED = "memory.consolidated"
    # Perception
    PERCEPTION_SENSED = "perception.sensed"
    # ... 28 more
```

**Key Invariant:** `MODEL ≠ AGENT` — the model is a component that reasons about state; it doesn't write state directly.

### 1.2 Hermes Agent: Phase-Decomposed ReAct

**Philosophy:** "The agent loop is a state machine decomposed into 25+ discrete phase handlers."

```python
# agent/conversation_loop.py
class AIAgent(
    ClientLifecycleMixin, StreamDeliveryMixin, StatusOutputMixin,
    ApiRequestHooksMixin, ApiErrorSummaryMixin, InterruptControlMixin,
    TurnExplainersMixin, ActivityTrackingMixin, RateLimitCreditsMixin,
    SessionPersistenceMixin, CompressionFacadeMixin, TurnFacadeMixin,
    VisionMessagePrepMixin, ReasoningParamsMixin,
):
    """Facade assembled from mixins — the loop lives in conversation_loop.py"""

def run_conversation(agent, ...):
    """Main loop with phase handlers."""
    while (s.api_call_count < agent.max_iterations
           and agent.iteration_budget.remaining > 0):
        # Each phase returns (action, result) where action ∈ {continue, break, return}
        _run_phase(begin_iteration, agent, s)
        _run_phase(prepare_iteration, agent, s)
        _run_phase(assemble_api_request, agent, s)
        
        # Inner retry loop for ONE API call
        result = _run_api_retry_loop(agent, s)
        if result is not None:
            return result
        
        # Phase: normalize response → tool round or finish
        _run_phase(normalize_model_response, agent, s)
        _run_phase(
            run_tool_round if s.assistant_message.tool_calls
            else finish_text_response,
            agent, s
        )
```

**25+ Phase Files:**
```
agent/
├── turn_iteration_prep.py      # Begin/prepare each iteration
├── turn_request_assembly.py    # Build API request payload
├── turn_api_request.py         # Request construction
├── turn_api_call.py            # The actual LLM call
├── turn_api_error.py           # API error classification & recovery
├── turn_response_intake.py     # Normalize model response
├── turn_response_check.py      # Validate response
├── turn_tool_round.py          # Execute tool calls
├── turn_tool_validation.py     # Validate tool arguments
├── turn_empty_response.py      # Handle empty responses
├── turn_overflow.py            # Context window overflow recovery
├── turn_truncation.py          # Response truncation recovery
├── turn_context_compaction.py  # Context compression triggers
├── turn_recovery.py            # Error recovery strategies
├── turn_recovery_autorecover.py # Auto-recovery ladder
├── turn_retry_state.py         # Retry state management
├── turn_stop_gates.py          # Loop termination conditions
├── turn_liveness.py            # Activity tracking
├── turn_usage.py               # Token usage tracking
├── turn_final_response.py      # Final response formatting
├── turn_finalizer.py           # Post-loop cleanup
├── turn_summary.py             # Turn summarization
├── turn_scripted_prelude.py    # Pre-turn scripted tool calls
└── turn_loop_errors.py         # Outer loop error handling
```

**Error Classification** (`error_classifier.py`):
```python
class FailoverReason(Enum):
    auth = "auth"
    billing = "billing"
    rate_limit = "rate_limit"
    overloaded = "overloaded"
    server_error = "server_error"
    timeout = "timeout"
    context_overflow = "context_overflow"
    content_policy_blocked = "content_policy_blocked"
    # ... 20+ specific reasons
```

**Strengths:**
- Extremely granular error handling
- Segment planner for parallel-safe tool batches
- Rich error classification → intelligent fallback

**Weaknesses:**
- Mutable state objects (not event-sourced)
- No persistent world model
- Proactive behavior bolted on via cron

### 1.3 OpenClaw: Tool-Loop with Abort Signals

**Philosophy:** "The agent loop is a simple tool-execution loop with abort signals and steering queues."

```typescript
// packages/agent-core/src/agent-loop.ts
async function runLoop(
  state: { context: AgentContext },
  newMessages: AgentMessage[],
  config: AgentLoopConfig,
  signal: AbortSignal | undefined,
  emit: AgentEventSink,
): Promise<AgentMessage[]> {
  let firstTurn = true;
  
  while (true) {
    let hasMoreToolCalls = firstTurn;
    
    while (hasMoreToolCalls || pendingMessages.length > 0) {
      if (await stopIfAborted()) return newMessages;
      
      // Stream model response
      const streamed = await streamAgentResponse(state.context, config, signal, emit);
      
      // Execute tool calls
      const executedToolBatch = await executeToolCalls(
        state.context,
        assistantMessage,
        config,
        signal,
        emit,
        toolLoopRecoveryState,
        toolPlan,
        toolCalls,
      );
      
      // Continue if tools were called
      hasMoreToolCalls = streamed.continuationRequired || !executedToolBatch?.terminate;
    }
    
    await emit({ type: "turn_end", message: terminalMessage, toolResults });
    await emit({ type: "agent_end", messages: newMessages });
    return newMessages;
  }
}

// Agent class with steering/follow-up queues
class Agent {
  state: AgentState;
  private steeringQueue = new PendingMessageQueue();
  private followUpQueue = new PendingMessageQueue();
  
  prompt(messages): Promise<AgentMessage[]> {
    // Throws if already processing
  }
  
  steer(messages): void {   // Queue for next turn checkpoint
    this.steeringQueue.enqueue(messages);
  }
  
  followUp(messages): void { // Queue for after current turn
    this.followUpQueue.enqueue(messages);
  }
}
```

**Strengths:**
- Clean abort signal handling
- Steering/follow-up queues for user interruption
- Simple, understandable loop

**Weaknesses:**
- No event sourcing
- No persistent entity state
- Proactive behavior only via cron jobs

---

## 2. Proactive Intelligence — THE KEY DIFFERENTIATOR

### 2.1 JaegerAI: Native Proactive Architecture ✅✅✅

**Philosophy:** "The entity acts from sensor events, background monitoring, and a heartbeat — not just from prompts."

```python
# jaeger_ai/core/runtime/initiative.py
"""One initiative pipeline: typed Initiative -> coded interruption policy.

Heartbeat, cron, webhooks and the Tier 3 sensor bus each produce a typed
Initiative. The InterruptionPolicy decides in code (never the model)
whether to speak now, hold, journal or drop.
"""

@dataclass(frozen=True)
class Initiative:
    """Something Jaeger might want to say, before any model sees it."""
    source: str           # sensor | heartbeat | cron | webhook | manual
    kind: str             # e.g. test_failed, disk_low, heartbeat
    summary: str
    level: SalienceLevel  # NOISE | JOURNAL | DIGEST | IMMEDIATE
    details: dict[str, Any]
    created_at: float
    dedupe_key: str       # SHA256-based deduplication

class InterruptionPolicy:
    """Deterministic gate for proactive speech. Persists across restarts."""
    def __init__(self, state_dir, *, quiet_hours=None, max_per_hour=6, ...):
        self.quiet_hours = quiet_hours or QuietHours(23, 7)  # 11pm-7am
        self.max_per_hour = max_per_hour
        self._state = load_state(state_dir)
    
    def decide(self, initiative: Initiative) -> Decision:
        """Deterministic decision: deliver | hold | journal | drop."""
        # 1. Dispatch by level
        # 2. Urgent bypasses quiet hours
        # 3. Rate budget check
        # 4. Deduplication check
        # 5. Quiet hours check
        # ... returns Decision(verdict, reason)

def compose_prompt(initiative: Initiative) -> str:
    """The talker prompt. It has NO tools; can only compose one message."""
    return f"""
    You are Jaeger, starting a conversation with {operator_name} on your own
    initiative. You have no tools in this turn: you can only write one
    short message to them.
    
    Write it like a person texting a friend they work with...
    If this is not worth interrupting them for, reply with exactly NO_MESSAGE.
    """
```

**Proactive Sources:**

| Source | Trigger | Example |
|--------|---------|---------|
| **Heartbeat** | Every N seconds | "Everything looks good" or idle processing |
| **Sensor Bus** | File changes, system events | "I noticed you edited config.yaml" |
| **Cron Jobs** | Scheduled prompts | "Daily standup summary" |
| **Webhooks** | External events | "GitHub PR merged" |
| **Missions** | Long-running goals | "Step 3 of 5 completed" |
| **Idle Supervisor** | No activity for X min | "Want me to clean up old files?" |
| **Background Producers** | Lease-gated producers | Heartbeat, cron, webhooks |
| **Reasoning Engine** | Cognitive loop on ticks | Autonomous thought processing |

**Salience Classification** (tiered, deterministic + LLM fallback):
```python
# jaeger_ai/core/runtime/salience.py
class SalienceLevel(IntEnum):
    NOISE = 0      # Drop entirely
    JOURNAL = 1    # Log only, no notification
    DIGEST = 2     # Batch for later delivery
    IMMEDIATE = 3  # Interrupt the operator now

class SalienceClassifier:
    def classify(self, event: SalienceEvent) -> SalienceLevel:
        # Fast deterministic rules first (no LLM cost)
        level = self.rules(event)
        if level is not None:
            return level
        # LLM fallback for ambiguous cases
        return self.model_evaluator(event)
    
    def rules(self, event) -> SalienceLevel | None:
        kind = event.kind.lower()
        
        # Test failures are always immediate
        if kind in {"test_failed", "build_failed", "deploy_failed"}:
            return SalienceLevel.IMMEDIATE
        
        # System critical events
        if kind in {"disk_low", "memory_pressure_critical", "service_down"}:
            return SalienceLevel.IMMEDIATE
        
        # File changes: autosaves are noise
        if kind in {"file_changed", "file_added", "file_deleted"}:
            if any(hint in path for hint in ("autosave", ".swp", "~", ".tmp")):
                return SalienceLevel.NOISE
            return SalienceLevel.JOURNAL
        
        # Git events
        if kind == "branch_changed":
            return SalienceLevel.DIGEST
        
        return None  # Fall to LLM
```

**Key Innovation:** The initiative pipeline is **typed and coded** — the model doesn't decide whether to interrupt; the `InterruptionPolicy` does (deterministic, auditable, restart-safe).

### 2.2 Hermes Agent: Cron-Driven Proactivity ⚠️

**Philosophy:** "The agent wakes up on a 60-second ticker and runs scheduled jobs."

```python
# cron/scheduler_provider.py
class InProcessCronScheduler(CronScheduler):
    def start(self, stop_event, *, interval=60, ...):
        """Default in-process 60s ticker."""
        while not stop_event.is_set():
            # Tick EVERY profile's store
            for store in all_profile_stores:
                due_jobs = store.tick(now)
                for job in due_jobs:
                    self._fire_job(job)
            
            stop_event.wait(interval)

# Jobs are claimed with durable CAS (at-most-once execution)
def claim_fire(job_id: str, *, force=False, manual=False) -> dict | None:
    """Durably claim one fire + create its audit attempt."""
    execution = create_execution(job_id, source=self.name)
    claimed_job = claim_job_for_fire(job_id, **claim_kwargs)
    return claimed_job
```

**Proactive Sources:**
- Cron jobs only (scheduled prompts)
- `/loop` command (recurring in-session wakeups)
- Webhook subscriptions
- Kanban task assignments

**Weakness:** No native sensor bus, no heartbeat-driven initiative, no salience classification. It's **cron with extra steps**.

### 2.3 OpenClaw: Cron Jobs + Dreaming ⚠️

**Philosophy:** "The gateway runs cron jobs that can initiate agent turns."

```typescript
// src/cron/service/scheduler-actor.ts
async function runCronSchedulerTick(state, connection) {
  // Evaluates all due jobs
  // Dispatches to:
  //   - runSessionEvent (system events)
  //   - runIsolatedAgentJob (agent turns)
  //   - runScriptJob (external scripts)
  //   - sendCronWebhook (HTTP webhooks)
}

// src/auto-reply/heartbeat.ts (DEPRECATED → migrated to cron)
export const HEARTBEAT_PROMPT = `
  ${HEARTBEAT_CONTEXT_PROMPT}
  If nothing needs attention, reply NO_REPLY.
`;
// NO_REPLY suppresses the message
```

```typescript
// Cron job structure
type CronJobBase = {
  id: string;
  name: string;
  enabled: boolean;
  schedule: TSchedule;  // { kind: "cron", expr } | { kind: "every", everyMs }
  sessionTarget: "main" | "isolated" | "current" | `session:${key}`;
  wakeMode: "now" | "next-heartbeat";
  payload: { kind: "systemEvent", text } | { kind: "agentTurn", message };
  delivery?: { mode: "none" | "announce", channel, to };
};
```

**Dreaming** (memory consolidation):
```typescript
// extensions/memory-core/src/dreaming-phases.ts
const DEEP_RANKING_SIGNALS = {
  relevance: 0.30,          // Retrieval quality
  frequency: 0.24,          // Short-term signal count
  queryDiversity: 0.15,     // Distinct recall queries
  recency: 0.15,            // Time-decayed freshness
  consolidation: 0.10,      // Multi-day recurrence
  conceptualRichness: 0.06, // Concept-tag density
};
// Three phases: light → REM → deep
// Writes to MEMORY.md with validation gates
```

**Proactive Sources:**
- Cron jobs (main feature)
- Hooks (shell-script triggers)
- Webhooks
- Subagent completion announcements
- System events

**Weakness:** No sensor-driven initiative, no salience classification, heartbeat deprecated in favor of cron.

---

## 3. Memory Architecture

### 3.1 JaegerAI: 5-Class Epistemic Memory ✅✅✅

**Philosophy:** "MEMORY ≠ CONTEXT WINDOW. OBSERVATION ≠ CLAIM ≠ BELIEF ≠ FACT."

```python
# jaeger_ai/core/entity/memory.py
class MemoryClass(str, Enum):
    WORKING = "working"        # Active turn context — ephemeral
    EPISODIC = "episodic"      # Chronological event history — immutable
    SEMANTIC = "semantic"      # Structured knowledge — versioned claims
    REFLECTIVE = "reflective"  # Meta-cognitive insights — from failures
    PROCEDURAL = "procedural"  # Verified skills/procedures — executable

class MemorySubsystem:
    def remember(self, class_: MemoryClass, payload: dict) -> MemoryRecord:
        """Write to the appropriate store."""
        if class_ == MemoryClass.EPISODIC:
            return self.event_store.append_event(payload)
        if class_ == MemoryClass.SEMANTIC:
            return self.semantic_store.add_claim(payload)
        if class_ == MemoryClass.REFLECTIVE:
            return self.reflexion_store.add_reflection(payload)
        # ... etc
    
    def recall(self, query: str, *, classes: list[MemoryClass] | None = None,
               budget_tokens: int = 2048) -> RecallResult:
        """Search across all memory classes."""
        # Semantic search + FTS + relevance scoring
        # Return with provenance tags
```

**World Model** (`jaeger_ai/core/world/`):
```python
# Epistemic layering: observation → claim → belief → fact
class EpistemicStatus(str, Enum):
    OBSERVATION = "observation"   # Raw sensor data, unverified
    CLAIM = "claim"               # Asserted by someone, not verified
    BELIEF = "belief"             # Internally held, may be wrong
    FACT = "fact"                 # Verified, high confidence

class WorldStore:
    def observe(self, source: str, data: dict) -> Observation:
        """Record raw observation."""
    
    def claim(self, source: str, statement: str, confidence: float) -> Claim:
        """Record a claim (may be from external source)."""
    
    def believe(self, statement: str, evidence: list[str]) -> Belief:
        """Form internal belief from evidence."""
    
    def verify(self, claim: Claim, probe: VerificationProbe) -> Fact | None:
        """Verify a claim; promote to FACT if verified."""
    
    def query(self, pattern: str) -> list[WorldEntity]:
        """Query the world model."""
```

**ContextCompiler** (SELECT → RANK → BUDGET → PROVENANCE → FORMAT):
```python
class ContextCompiler:
    def compile(self, goal: str, *, budget_tokens: int = 4096, ...) -> CompiledContext:
        # 1. SELECT: Gather candidates from all memory subsystems
        items = self.select(goal, ...)
        
        # 2. RANK: Deterministic priority + salience ordering
        ranked = self.rank(items)
        
        # 3. BUDGET: Enforce token limits
        included, dropped = self.budget(ranked, budget_tokens)
        
        # 4. PROVENANCE: Tag every item with source
        # 5. FORMAT: Render for cognition
        return self.format_for_cognition(goal, included, dropped, budget_tokens)
```

**Priority Tiers:**
1. Identity (always included)
2. Runtime Truth / Capabilities
3. Self State
4. Learned Skills
5. Reflections
6. Semantic Claims
7. Retrieved Documents
8. Device Observations
9. Recent Events

### 3.2 Hermes Agent: Curated Files + FTS5

**Philosophy:** "Memory is files (MEMORY.md, USER.md) + full-text search over sessions."

```python
# Memory structure:
~/.hermes/
├── MEMORY.md          # Curated long-term memory (agent-maintained)
├── USER.md            # User profile/preferences
├── sessions/          # FTS5-searchable session transcripts
└── skills/            # Learned skills
```

**FTS5 Session Search:**
```python
# Uses SQLite FTS5 for full-text search across all sessions
# No semantic/vector search in core (external providers optional)
SELECT * FROM sessions_fts 
WHERE sessions_fts MATCH ? 
ORDER BY rank;
```

**External Memory Providers:**
- Honcho, Hindsight, Supermemory, Mem0, OpenViking, Holographic, Retaindb, Byterover

**Weakness:** No epistemic layering, no world model, no deterministic state projection.

### 3.3 OpenClaw: Files + Dreaming

**Philosophy:** "Memory is MEMORY.md + daily notes + background consolidation (dreaming)."

```typescript
// Memory structure:
~/.openclaw/
├── MEMORY.md              # Long-term memory
├── USER.md                # User profile
├── memory/
│   ├── 2026-10-25.md      # Daily notes
│   └── ...
└── state/openclaw.sqlite  # Session metadata
```

**Dreaming Phases:**
```typescript
// 1. Light: Sort and stage recent material (no writes)
// 2. REM: Reflect on themes (no writes)
// 3. Deep: Score and promote to MEMORY.md (with validation)

const DEEP_RANKING_SIGNALS = {
  relevance: 0.30,
  frequency: 0.24,
  queryDiversity: 0.15,
  recency: 0.15,
  consolidation: 0.10,
  conceptualRichness: 0.06,
};
```

**External Providers:**
- Honcho, LanceDB, memory-wiki (plugins)

**Weakness:** No event sourcing, no epistemic layers, no deterministic state.

---

## 4. Verification & Trust

### 4.1 JaegerAI: Independent Verification Probes ✅✅✅

**Philosophy:** "TOOL SUCCESS ≠ VERIFIED SUCCESS. Independent probes verify claims."

```python
# jaeger_ai/core/effects/verification.py
class VerificationProbe(Protocol):
    def probe(self, claim: EffectClaim) -> VerificationResult:
        """Independent verification of an effect claim."""
        pass

class DiskProbe(VerificationProbe):
    """Verify file effects by reading from disk."""
    def probe(self, claim: EffectClaim) -> VerificationResult:
        path = Path(claim.target)
        if not path.exists():
            return VerificationResult(verified=False, reason="file missing")
        content = path.read_text()
        expected = claim.expected_content
        return VerificationResult(
            verified=content == expected,
            actual=content[:100],
            expected=expected[:100]
        )

class GitProbe(VerificationProbe):
    """Verify git operations by checking git state."""
    
class ProcessProbe(VerificationProbe):
    """Verify process execution by checking process list."""

class VerificationRegistry:
    def register(self, probe_type: str, probe: VerificationProbe):
        self._probes[probe_type] = probe
    
    def verify(self, claim: EffectClaim) -> VerificationResult:
        probe = self._probes.get(claim.probe_type)
        if not probe:
            return VerificationResult(verified=False, reason="no probe")
        return probe.probe(claim)
```

**EffectLedger** — idempotent effect tracking:
```python
# jaeger_ai/core/effects/ledger.py
class EffectLedger:
    """Append-only ledger of all effects (idempotent by key)."""
    
    def record(self, effect: Effect) -> EffectRecord:
        """Record an effect with idempotency key."""
        # SHA256 of (tool, args, session) = idempotency key
        # If key exists, return existing record (no duplicate)
        # Otherwise, append to ledger
    
    def verify(self, effect_id: str) -> VerificationResult:
        """Verify an effect using registered probes."""
        record = self.get(effect_id)
        return self.verification_registry.verify(record.claim)
```

### 4.2 Hermes Agent: Tool Return Strings ⚠️

**Philosophy:** "The tool tells us if it succeeded."

```python
# Tools return:
{"success": True, "output": "...", "error": None}
# The agent trusts this — no independent verification
```

### 4.3 OpenClaw: Tool Return Strings ⚠️

**Philosophy:** "The tool tells us if it succeeded."

```typescript
// Tools return ToolResult:
interface ToolResult {
  success: boolean;
  output: string;
  error?: string;
}
// No independent verification probes
```

---

## 5. Multi-Agent Architecture

### 5.1 JaegerAI: Native Multi-Agent ✅✅✅

```python
# jaeger_ai/features/roundtable/ — Multi-agent debate & consensus
class TableService:
    """Multi-agent roundtable for complex decisions."""
    
    def debate(self, topic: str, *, agents: list[str], rounds: int = 3) -> ConsensusResult:
        """Run a structured debate between multiple agent personas."""
        # Round 1: Opening statements
        # Round 2: Rebuttals
        # Round 3: Synthesis
        # Consensus extraction
        
# jaeger_ai/features/dispatcher/ — Task dispatch & Kanban
class Dispatcher:
    """Route tasks to specialized agents."""
    
    def dispatch(self, task: TaskCard) -> AgentAssignment:
        """Assign task to best agent based on skills/workload."""
        
# jaeger delegate — External agent delegation
class DelegateRegistry:
    """Delegate to claude, codex, hermes, openclaw, gemini, etc."""
    
    def delegate(self, runtime: str, goal: str, **kwargs) -> DelegateResult:
        """Run a task on an external agent runtime."""
```

### 5.2 Hermes Agent: Subagents + Kanban ⚠️

```python
# Subagents via delegation tool
hermes delegate_task(runtime="...", goal="...")

# Kanban for multi-profile collaboration
hermes kanban boards | create | list | show | assign | claim

# /loop for recurring wakeups
hermes /loop 30m "check build status"
```

### 5.3 OpenClaw: Worktrees + Tasks ✅

```typescript
// Worktrees for parallel agents
openclaw worktrees list
openclaw agents add work --workspace ~/work

// Tasks/workboard
openclaw tasks list
openclaw workboard

// Nodes (mobile as remote workers)
openclaw nodes camera snap --node <id>
openclaw nodes screen record --node <id>
```

---

## 6. Architecture Comparison Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         JAEGERAI                                │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐│
│  │   SENSORS   │───▶│   EVENT     │───▶│  EVENT STORE        ││
│  │  (heartbeat)│    │   FABRIC    │    │  (append-only SQL)  ││
│  │  (cron)     │    │             │    │                     ││
│  │  (webhooks) │    └──────┬──────┘    └──────────┬──────────┘│
│  │  (idle)     │           │                      │           │
│  └─────────────┘           ▼                      ▼           │
│                    ┌─────────────┐    ┌─────────────────────┐ │
│                    │   SELF      │◀───│  REPLAY EVENTS      │ │
│                    │   STATE     │    │  (pure reducers)    │ │
│                    │ (deterministic)   └─────────────────────┘ │
│                    └──────┬──────┘                            │
│                           ▼                                   │
│                    ┌─────────────┐    ┌─────────────────────┐ │
│                    │  SALIENCE   │───▶│  COGNITION ROUTER   │ │
│                    │  ENGINE     │    │  (strategy dispatch)│ │
│                    └─────────────┘    └──────────┬──────────┘ │
│                                                  ▼            │
│                    ┌─────────────────────────────────────┐   │
│                    │     CONTEXT COMPILER                │   │
│                    │  (SELECT→RANK→BUDGET→PROVENANCE→FMT)│   │
│                    └─────────────────┬───────────────────┘   │
│                                      ▼                        │
│                         ┌─────────────────────┐               │
│                         │    JAEGER AGENT     │               │
│                         │   (subordinate ReAct)│              │
│                         │  + PolicyKernel     │               │
│                         │  + EffectLedger     │               │
│                         │  + Verification     │               │
│                         └─────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       HERMES AGENT                              │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐│
│  │   CRON      │───▶│   SCHEDULER │───▶│   JOB QUEUE         ││
│  │  (60s tick) │    │  (ticker)   │    │  (durable claims)   ││
│  └─────────────┘    └─────────────┘    └──────────┬──────────┘│
│                                                    ▼           │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐│
│  │   MEMORY    │◀───│   SESSION   │◀───│   AGENT LOOP        ││
│  │  (SQLite)   │    │   (SQLite)  │    │  (phase handlers)   ││
│  └─────────────┘    └─────────────┘    └─────────────────────┘│
│                              ▲                              │
│                              │                              │
│                    ┌─────────┴─────────┐                      │
│                    │  MESSAGE FROM     │                      │
│                    │  USER/CHANNEL     │                      │
│                    └───────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         OPENCLAW                                │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐│
│  │  CHANNELS   │───▶│   GATEWAY   │───▶│  SESSION STORE      ││
│  │ (30+ adapters│   │  (WebSocket)│    │  (SQLite)           ││
│  └─────────────┘    └──────┬──────┘    └─────────────────────┘│
│                            ▼                                    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐│
│  │   CRON      │───▶│   CRON      │───▶│   AGENT RUNTIME     ││
│  │  (jobs)     │    │   SERVICE   │    │  (tool loop)        ││
│  └─────────────┘    └─────────────┘    └─────────────────────┘│
│                              ▲                              │
│  ┌─────────────┐    ┌────────┴────────┐                       │
│  │   MEMORY    │◀───│  MESSAGE TO/FROM│                       │
│  │ (files+SQLite)  │  USER/CHANNEL   │                       │
│  └─────────────┘    └─────────────────┘                       │
│  + DREAMING (background consolidation)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. What Makes Each "Agentic"?

### JaegerAI: **Proactive World-Model Entity**

**The agentic paradigm:**
- **Persistent identity** — survives restarts, model swaps, interface changes
- **Event-sourced state** — deterministic replay, crash-safe
- **Native proactive intelligence** — sensors, heartbeat, initiative pipeline
- **Epistemic memory** — observation ≠ claim ≠ belief ≠ fact
- **Independent verification** — tool success ≠ verified success
- **Simulation-first** — propose → simulate → verify → approve → act

**Key code pattern:**
```python
# The entity WAKES ITSELF based on salience
decision = salience_engine.evaluate(event, state)
if decision.wake_cognition:
    cognition_router.execute(strategy, event, decision, state, ...)
```

### Hermes Agent: **Self-Improving Agent**

**The agentic paradigm:**
- **Learning loop** — creates skills from experience, improves them
- **Multi-platform gateway** — one agent, 20+ messaging channels
- **Cron-driven autonomy** — scheduled self-initiated tasks
- **Rich tool ecosystem** — 60+ tools, 6 terminal backends

**Key code pattern:**
```python
# The scheduler TICKS and fires jobs
while not stop_event.is_set():
    due_jobs = store.tick(now)
    for job in due_jobs:
        run_agent_conversation(job.prompt)  # Scheduled autonomy
    stop_event.wait(interval)
```

### OpenClaw: **Personal AI Gateway**

**The agentic paradigm:**
- **Always-on daemon** — single gateway process, multiplexed WebSocket
- **Multi-device nodes** — phones/desktops as tool providers
- **Channel abstraction** — 30+ messaging platforms uniformly
- **Memory dreaming** — background consolidation

**Key code pattern:**
```typescript
// The gateway RECEIVES messages and dispatches to agents
gateway.on('message', async (msg) => {
  const session = await resolveSession(msg);
  await agent.prompt(session.transcript);
});
```

---

## 8. Feature Parity: Proactive Intelligence

| Feature | JaegerAI | Hermes | OpenClaw | Winner |
|---------|----------|--------|----------|--------|
| **Native sensors** | ✅ Sensor bus | ❌ | ❌ | **JaegerAI** |
| **Heartbeat-driven initiative** | ✅ Native | ⚠️ Cron only | ⚠️ Deprecated→cron | **JaegerAI** |
| **Salience classification** | ✅ Tiered + LLM | ❌ | ❌ | **JaegerAI** |
| **InterruptionPolicy** | ✅ Deterministic, auditable | ❌ | ❌ | **JaegerAI** |
| **Deduplication** | ✅ SHA256-based | ✅ | ✅ | Tie |
| **Quiet hours** | ✅ Configurable | ⚠️ Active hours | ⚠️ Active hours | Tie |
| **Rate budgeting** | ✅ Per-hour limits | ❌ | ❌ | **JaegerAI** |
| **World model** | ✅ Epistemic layers | ❌ | ❌ | **JaegerAI** |
| **Event sourcing** | ✅ 40+ event types | ❌ | ❌ | **JaegerAI** |
| **Deterministic state** | ✅ Pure reducers | ❌ | ❌ | **JaegerAI** |
| **Memory consolidation** | ⚠️ ReflexionStore | ⚠️ Curator | ✅ Dreaming | OpenClaw |
| **Self-improving skills** | ✅ Skill improvement | ✅ **Superior** | ✅ Workshop | Hermes |
| **Simulation-first approval** | ✅ **Native** | ❌ | ❌ | **JaegerAI** |
| **Independent verification** | ✅ Probes | ❌ | ❌ | **JaegerAI** |
| **Multi-agent debate** | ✅ Roundtable | ❌ | ❌ | **JaegerAI** |
| **Cron scheduling** | ✅ | ✅ | ✅ | Tie |
| **Webhooks** | ✅ | ✅ | ✅ | Tie |
| **Mobile nodes** | ❌ | ⚠️ Mobile apps | ✅ **Superior** | OpenClaw |

---

## 9. Verdict: Which is More "Agentic"?

### The Hierarchy of Agentic Intelligence

```
Level 5: PROACTIVE WORLD-MODEL ENTITY (JaegerAI)
         ↓  Acts from sensors, heartbeat, world model
         ↓  Simulation-first, independent verification
         ↓  Persistent identity, event-sourced state
         ↓  Typed initiative pipeline, salience classification

Level 4: SELF-IMPROVING AGENT (Hermes Agent)
         ↓  Learns from experience, creates skills
         ↓  Cron-driven autonomy
         ↓  Multi-platform gateway
         ↓  Phase-decomposed ReAct loop

Level 3: PERSONAL AI GATEWAY (OpenClaw)
         ↓  Always-on daemon, multi-device nodes
         ↓  Channel abstraction, memory dreaming
         ↓  Cron jobs, hooks

Level 2: TOOL-USING CHATBOT (Most "AI assistants")
         ↓  Turn-based, reactive
         ↓  No persistent state, no autonomy

Level 1: CHATBOT (Simple)
         ↓  Pure conversation, no tools
```

### JaegerAI is Architecturally Superior for True Agency

**Why JaegerAI is more "agentic":**

1. **Event-Sourced State** — State is reconstructed from events. Hermes/OpenClaw use mutable objects.
2. **Native Proactive Intelligence** — Sensors + heartbeat + initiative pipeline. Hermes/OpenClaw bolt it on via cron.
3. **World Model** — Epistemic layers (observation/claim/belief/fact). Neither Hermes nor OpenClaw has this.
4. **Deterministic State Reduction** — Pure functions, replay-safe. Hermes/OpenClaw are imperative.
5. **Independent Verification** — Tool success ≠ verified success. Hermes/OpenClaw trust tool returns.
6. **Simulation-First Approval** — For physical work: propose → simulate → verify → approve → act. Unique to JaegerAI.
7. **Salience Classification** — Tiered, deterministic + LLM fallback. Neither has this.
8. **InterruptionPolicy** — Coded, auditable, restart-safe decisions about when to interrupt.

**What Hermes/OpenClaw do better:**
- Hermes: Self-improving skills (learning loop), more messaging platforms
- OpenClaw: Mobile nodes (phone camera/screen as tools), more channels

---

## 10. Recommendation

### For Jenkins Robotics Use Case:

**✅ JaegerAI is the correct choice** for these reasons:

1. **Robotics integration** — Native JROS support (unique)
2. **Proactive intelligence** — Sensors, heartbeat, world model (superior)
3. **Physical embodiment** — Simulation-first approval (unique)
4. **On-device trust** — Memory, approvals, audit stay local (superior)
5. **YouTube/business ops** — Content pipeline (unique)
6. **Multi-surface clients** — Mac/Web/TUI/IDE/Voice (superior)

### Migration Strategy:

**Phase 1: Fill Messaging Gaps (2-4 weeks)**
- Port WhatsApp, Signal, Matrix from OpenClaw
- Upgrade Slack to full implementation

**Phase 2: Fill Mobile Gap (2-3 months)**
- Build iOS/Android node apps (port OpenClaw's node protocol)

**Phase 3: Skills Ecosystem (1-2 months)**
- Integrate with ClawHub or agentskills.io
- Enhance self-improvement (port Hermes' learning loop patterns)

**Phase 4: Hybrid Features (as needed)**
- Add OpenClaw's dreaming to JaegerAI's memory system
- Add Hermes' phase-decomposed error handling to JaegerAgent

### Bottom Line:

**JaegerAI is already more "agentic" than Hermes + OpenClaw at the architectural level.** The gaps are in **breadth** (channels, mobile) not **depth** (proactive intelligence, world model, verification).

Fill the breadth gaps, and JaegerAI becomes the definitive choice.

---

*Deep technical comparison completed: 2026-10-25*
