# Agent Architecture & Sidebar Enhancement Plan — V2 (Audited)

**Date:** 2026-10-26
**Status:** Revised after critical audit
**Supersedes:** `AGENT_ARCHITECTURE_PLAN.md` (V1)

---

## What Changed from V1

| Issue | V1 Approach | V2 Fix |
|-------|-------------|--------|
| **Enum confusion** | New `AgentType.CHARACTER` enum | Use existing `AgentRole.CHARACTER` |
| **Pin vs Primary** | Conflated | Clear separation: PIN = favorites strip, PRIMARY = star badge, LEAD = execution role |
| **Security** | Tool toggle "advisory" | Enforced at Gateway via `AllowlistToolExecutor` |
| **Race conditions** | No concurrency control on type change | Optimistic locking + session termination on change |
| **Agent types** | "Character OR Specialist" (mutually exclusive) | "Role + optional Personality" (orthogonal) |
| **Migration** | Heuristic name matching | Explicit markers + version bump |

---

## Part 1: Understanding the Existing System (Audit)

### 1.1 Four Distinct Concepts (NOT Three)

After deep research, here are the **FOUR** separate concepts in JaegerAI:

| Concept | What It Is | Storage | Max | Visual |
|---------|-----------|---------|-----|--------|
| **PIN** | User favorites in top strip | localStorage (`jaeger.ui.pinned-agents`) OR server (`agent_presentation.pinned`) | 8 | Tile in pinned strip |
| **PRIMARY** | The "default" agent — gets star badge | Server (`schema_meta.agent_primary:operator` in SQLite) | 1 | ⭐ Star badge on avatar |
| **LEAD** | Execution role — plans and delegates | Registry (`AgentRole.LEAD`) | 1 (default `native:jaeger`) | Supervisor tile in pinned area |
| **SUPERVISOR** | UI label for the lead's tile | Client-side only | N/A | Tile labeled "Supervisor" |

**Key Insight:** PIN and PRIMARY are **different**!
- **Pin** = "I use this often" (favorites, like browser bookmarks)
- **Primary** = "This is MY agent" (identity, like a username)

Example: You might pin "Builder" (use it often) but your primary is "Jarvis" (your butler).

### 1.2 Visual Hierarchy in Current Sidebar

```
┌─────────────────────────────────────────┐
│  ⭐ PINNED STRIP (always at top)        │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐          │
│  │ ★  │ │ 🎩 │ │ 🔧 │ │ 📊 │          │  ← Supervisor tile (PRIMARY+LEAD)
│  │Jaeg│ │Jarv│ │Buil│ │Rese│          │    + PINNED agents (up to 7 more)
│  │ ⭐ │ │    │ │    │ │    │          │    (PRIMARY has star, others don't)
│  └────┘ └────┘ └────┘ └────┘          │
│     ↑                              ↑   │
│  Supervisor = PRIMARY + LEAD       Pinned = Favorites (localStorage)
├─────────────────────────────────────────┤
│  👔 SPECIALISTS (role: specialist)      │  ← Grouped by section
│  ── Section: "Project Alpha" ──         │
│  [🔧] Builder          ●               │  ← Unread dot
│  [🔍] Reviewer         ○               │
│                                         │
│  🎭 CHARACTERS (role: character)        │  ← NEW: Personality agents
│  [🎩] Jarvis            ○ [⚪ Tools]    │  ← Tool toggle indicator
│  [🔮] Lilith            ○ [⚫ Tools]    │
└─────────────────────────────────────────┘
```

---

## Part 2: Industry Comparison

### 2.1 How Grok Bot Handles It

| Feature | Grok Bot | JaegerAI (Current) | Gap |
|---------|----------|-------------------|-----|
| **Pinned bots** | Drag-to-pin, max unspecified | ✅ Drag-to-pin, max 8 | Match |
| **Primary/Default** | One bot is "primary" | ✅ Server-side, star badge | Match |
| **Bot marketplace** | `x.ai/bot/marketplace` with categories | ❌ Missing | **Add marketplace** |
| **Bot personality** | Model-side tone only (Grok/Aria/Jarvis personas) | ✅ Full personality system (20 chars) | **Jaeger is richer** |
| **Bot creation** | Marketplace "Add" button or from scratch | ✅ Gallery + templates | Match |
| **Sections** | Server-defined sections | ✅ `sections.ts` + `/v1/sections` | Match |
| **Unread** | Blue dot | ✅ `unread.ts` | Match |
| **⌘K Search** | Centered palette | ✅ `JumpTo.tsx` | Match |
| **Context menu** | Basic (Pin, Mark Read, Copy ID) | ✅ Richer (Pin, Rename, Hide, Delete, Move to section) | **Jaeger is richer** |

### 2.2 How Codex Handles It

| Feature | Codex | JaegerAI |
|---------|-------|----------|
| **Agent roles** | `default`, `worker`, `explorer` + custom TOML files | `LEAD`, `SPECIALIST`, `RUNTIME` + standing specialists |
| **Custom agents** | `.codex/agents/*.toml` (name, description, instructions, model, features) | Registry + `POST /v1/agents` |
| **Personality** | `developer_instructions` only | ✅ Full HEXACO/SPECIAL/Expression traits |
| **Tool gating** | Per-agent feature toggles (`shell_tool`, `apps`, `memories`) | ✅ Per-agent `allowed_tools` allowlist |
| **Handoffs** | `spawn_agent` tool with role + model overrides | ✅ `call_agent` / `delegate_task` |
| **Hierarchy** | Parent → child → grandchild (max depth enforced) | ✅ Lead → specialist (bounded) |
| **Cloud tasks** | Independent parallel sandboxes | ❌ Missing (future) |
| **Debate/Consensus** | ❌ No | ✅ **Roundtable (unique!)** |

**Key Takeaway:** JaegerAI's personality system is **richer** than Codex. Codex's TOML-based agent definitions are **cleaner** than Jaeger's registry approach. We should adopt **both**: TOML-style character definitions + Jaeger's personality traits.

### 2.3 How Hermes Agent Handles It

| Feature | Hermes | JaegerAI |
|---------|--------|----------|
| **Subagents** | `delegate_task(runtime=..., goal=...)` | ✅ `delegate_task` (similar) |
| **Kanban** | `hermes kanban` — multi-profile board | ❌ Missing |
| **Peer messaging** | `hermes peer` — bot-to-bot DMs | ✅ **Dispatcher (unique!)** |
| **Bot Mode** | Always-on gateway bot | ✅ Gateway daemon |

### 2.4 How OpenClaw Handles It

| Feature | OpenClaw | JaegerAI |
|---------|----------|----------|
| **Agents** | Multiple named profiles | ✅ Registry |
| **Worktrees** | `openclaw worktrees` — isolated workspaces | ❌ Missing |
| **Nodes** | iOS/Android connect as workers | ✅ **Mobile nodes (we built this!)** |
| **Channels** | 30+ messaging platforms | ✅ Channels system |

---

## Part 3: Revised Architecture (V2)

### 3.1 AgentRole Enum (Extended)

```python
# jaeger_ai/core/agent_registry/types.py

class AgentRole(str, Enum):
    """Product role — what the agent DOES and HOW it's displayed."""
    LEAD = "lead"           # Primary companion, plans and delegates
    SPECIALIST = "specialist"  # Task expert with tool allowlist
    CHARACTER = "character"    # NEW: Conversational persona (minimal tools)
    RUNTIME = "runtime"        # Background/runtime agent (hidden)
```

**Why `AgentRole.CHARACTER` instead of `AgentType`?**
- `AgentType` already exists in `multi_agent/models.py` (means: persistent vs worker)
- `AgentRole` is the **product-facing** concept (what users see in sidebar)
- Adding `CHARACTER` to `AgentRole` is **backward compatible** (new enum value)

### 3.2 Decoupled: Role + Personality

**Key insight:** An agent's **role** (what it does) is **orthogonal** to its **personality** (who it is).

```python
# Every agent has:
agent.role          # AgentRole (LEAD | SPECIALIST | CHARACTER | RUNTIME)
agent.personality   # Optional[CharacterPersonality] — from character library

# Examples:
lead_agent.role = AgentRole.LEAD
lead_agent.personality = CharacterPersonality(template="jarvis")  # Optional!

specialist_agent.role = AgentRole.SPECIALIST
specialist_agent.personality = CharacterPersonality(template="glados")  # Sarcastic reviewer!

character_agent.role = AgentRole.CHARACTER
character_agent.personality = CharacterPersonality(template="lilith")  # No tools
# character_agent.personality = None  # Possible: custom character
```

**This allows:**
- Jarvis as a **personality** on the Lead agent (butler who can also code)
- GLaDOS as a **specialist** (sarcastic code reviewer with reviewer tools)
- Lilith as a **character** (no tools, pure conversation)
- Custom characters with **no template** (just a name + instructions)

### 3.3 Tool Policy (Enforced, Not Advisory)

```python
# jaeger_ai/core/agent_registry/specialists.py

def effective_tools(agent: AgentRecord) -> list[str] | None:
    """The tools this agent can actually use.
    
    None = inherit from parent/context (lead, runtime)
    []   = model-only (character with no tools)
    [...] = explicit allowlist
    """
    # 1. Explicit per-agent override (from tool toggle UI)
    if "tool_allowlist" in agent.metadata:
        tools = agent.metadata["tool_allowlist"]
        return [] if tools is None else list(tools)
    
    # 2. Character role default: NO TOOLS
    if agent.role == AgentRole.CHARACTER:
        return []
    
    # 3. Specialist: standing tools or explicit set
    if agent.role == AgentRole.SPECIALIST:
        return specialist_tools(agent)  # Existing function
    
    # 4. Lead/Runtime: inherit (None = no restriction)
    return None
```

**Enforcement point:** `AllowlistToolExecutor` in `packages/jaeger-agent/jaeger_agent/tool_executor.py`

```python
# Gateway wraps every turn with the effective allowlist:
tools = effective_tools(agent)
with tool_allowlist(tools):  # None = unlimited, [] = no tools, [...] = subset
    result = await run_turn(agent, user_message)
```

**Security guarantee:** A character with `tools=[]` **cannot** call tools, even if the model hallucinates a tool call. The `AllowlistToolExecutor` **blocks** it.

### 3.4 Data Model

```python
# jaeger_ai/core/agent_registry/types.py

@dataclass(slots=True)
class AgentRecord:
    id: str
    name: str
    kind: AgentKind           # NATIVE | THIRD_PARTY
    display_name: str
    source: str
    role: AgentRole          # LEAD | SPECIALIST | CHARACTER | RUNTIME (extended)
    workspace_id: str | None
    perspective_id: str | None
    # ... existing fields ...
    
    # NEW: Personality (optional, from character library)
    personality: CharacterPersonality | None = None  # Serialized as metadata["personality"]
    
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata keys:
    #   "character_template": str | None  — Template ID (jarvis, lilith, etc.)
    #   "tool_allowlist": list[str] | None — Explicit tool override (None = inherit)
    #   "personality": dict | None          — Serialized CharacterPersonality
    #   "personality_version": int         — For template updates

@dataclass(slots=True)
class CharacterPersonality:
    """Personality overlay from the character library."""
    template_id: str | None      # "jarvis", "lilith", etc. (None = custom)
    name: str                     # Display name
    role_description: str         # "the operator's AI butler"
    voice_tone: str              # "crisp, dry, British-butler"
    voice_id: str                # "bm_george" (for TTS)
    backstory: str               # Short version for prompt
    soul: str                    # Core narrative (if exists)
    traits: PersonalityTraits    # HEXACO + SPECIAL + Expression + Domains
    speech_patterns: tuple[str, ...]
    quotes: tuple[str, ...]
    
    # For rendering:
    card_url: str | None         # "/v1/characters/jarvis/card"
    card_thumbnail_url: str | None
```

---

## Part 4: Sidebar Design (Merged: Apple + Grok)

### 4.1 Section Order (Fixed)

```
1. ⭐ PINNED STRIP (always visible)
   └── Supervisor tile (PRIMARY + LEAD) + up to 7 pinned agents
   
2. 👑 LEAD AGENT (if not in pinned strip)
   └── The primary agent (star badge)
   
3. 👔 SPECIALISTS (role: specialist)
   └── Grouped by section, sorted by activity
   
4. 🎭 CHARACTERS (role: character)
   └── Grouped by section, sorted by name
   
5. 📦 ARCHIVED (collapsed, at bottom)
   └── Hidden agents (soft-deleted)
```

### 4.2 Agent Row Visual Design

**Specialist row:**
```
┌─────────────────────────────────────┐
│ [🛠️]  Builder              ●       │  ← Avatar (gradient), name, unread dot
│       Code & implementation         │  ← Status/role description
│       ─────────────────────         │     (secondary text)
│       Last message preview...       │  ← Preview (tertiary text)
└─────────────────────────────────────┘
```

**Character row:**
```
┌─────────────────────────────────────┐
│ [🎩]  Jarvis              ●  [⚪]   │  ← Card thumbnail (32×42), name, unread, TOOL TOGGLE
│       AI Butler               👔    │  ← Role + type badge (🎭 = character, 👔 = specialist)
│       "I've taken the liberty..."   │  ← Signature quote (personality indicator)
└─────────────────────────────────────┘
         ↑
    Card thumbnail (not gradient avatar)
    Shows actual card.png
```

### 4.3 Context Menu (Right-Click)

**Specialist agent:**
```
├── Pin / Unpin
├── Move to [section] ›
├── ─────────────────
├── Mark as Read / Mark as Unread
├── ─────────────────
├── Rename
├── Add Personality ›  ← NEW: Attach character personality
├── ─────────────────
├── View Details
├── Chat History
├── ─────────────────
├── Copy Agent ID
├── ─────────────────
├── Hide from Sidebar
├── Delete (danger)
└── Make Primary (if not already)
```

**Character agent:**
```
├── Pin / Unpin
├── Move to [section] ›
├── ─────────────────
├── Mark as Read / Mark as Unread
├── ─────────────────
├── Rename
├── Edit Personality ›  ← NEW: Edit traits, voice, backstory
├── Toggle Tools ›      ← NEW: Enable/disable specific tools
│   ├── ☑ read_file
│   ├── ☑ search_files
│   ├── ☐ write_file
│   ├── ☐ terminal
│   └── [Enable All] [Disable All]
├── ─────────────────
├── View Details (full card modal)
├── ─────────────────
├── Copy Agent ID
├── ─────────────────
├── Convert to Specialist  ← NEW: Change role
├── Hide from Sidebar
├── Delete (danger)
└── Make Primary (if not already)
```

**Lead/Primary agent:**
```
├── Unpin (can't unpin supervisor)
├── ─────────────────
├── Mark as Read
├── ─────────────────
├── Rename
├── Change Personality ›  ← NEW: Lead can "wear" a character
├── ─────────────────
├── View Details
└── Replace with Different Bot (change primary)
```

### 4.4 ⌘K Search Palette

```
┌─────────────────────────────────────┐
│  🔍 Search agents...                │  ← Search input (focused)
├─────────────────────────────────────┤
│  QUICK ACTIONS                      │
│  ⌘N  New Chat                       │
│  ⌘,  Settings                       │
│  ⌘J  Open Chat                      │
├─────────────────────────────────────┤
│  AGENTS (5)                         │
│  [★]  Jaeger          Lead           │  ← Avatar, name, type, unread dot
│  [🎩] Jarvis          Character      │
│  [🔧] Builder         Specialist  ●  │
│  [🔍] Researcher      Specialist    │
│  [🎭] Lilith          Character      │
├─────────────────────────────────────┤
│  RECENTLY USED (3)                  │
│  [🔧] Builder (2m ago)              │
│  [★]  Jaeger  (5m ago)              │
│  [🎩] Jarvis  (1h ago)              │
├─────────────────────────────────────┤
│  [↑↓] Navigate  [↵] Select  [ESC] Close
└─────────────────────────────────────┘
```

---

## Part 5: API Changes (V2 — Corrected)

### 5.1 New Endpoints

```
GET   /v1/characters                 — List character templates (EXISTING)
GET   /v1/characters/{id}            — Get character details (EXISTING)
GET   /v1/characters/{id}/card       — Serve card.png (EXISTING)

POST  /v1/agents/from-character      — Create character agent (NEW — replaces /from-template)
POST  /v1/agents/from-specialist     — Create specialist agent (NEW)

PATCH /v1/agents/{id}/role           — Change agent role (NEW — with optimistic locking)
PATCH /v1/agents/{id}/personality    — Attach/detach character personality (NEW)
PATCH /v1/agents/{id}/tools          — Set tool allowlist (NEW — operator-only)
GET   /v1/agents/{id}/tools          — Get effective tool list (NEW)

GET   /v1/agents?filter=role:specialist  — Filter by role (NEW query param)
GET   /v1/agents?filter=has_personality  — Filter agents with personality (NEW)
```

### 5.2 Request/Response Examples

**Create character agent:**
```http
POST /v1/agents/from-character
{
    "template_id": "jarvis",
    "name": "My Jarvis",           // Optional: override display name
    "tools": []                     // Optional: explicit tool list ([] = no tools)
}
```

**Response:**
```json
{
    "id": "native:my-jarvis",
    "name": "my-jarvis",
    "display_name": "My Jarvis",
    "role": "character",
    "kind": "jaeger_native",
    "personality": {
        "template_id": "jarvis",
        "name": "Jarvis",
        "voice_tone": "crisp, dry, British-butler",
        "traits": {"hexaco": {...}, "special": {...}},
        "card_url": "/v1/characters/jarvis/card"
    },
    "effective_tools": [],           // Empty = no tools
    "metadata": {
        "character_template": "jarvis",
        "personality_version": 1
    }
}
```

**Toggle tools for character:**
```http
PATCH /v1/agents/native:my-jarvis/tools
{
    "allowed_tools": ["read_file", "search_files"],
    "expected_revision": 3          // Optimistic locking
}
```

**Response:**
```json
{
    "id": "native:my-jarvis",
    "effective_tools": ["read_file", "search_files"],
    "tool_scope": "explicit",
    "revision": 4
}
```

---

## Part 6: Security Model (Audited)

### 6.1 Threat Model

| Threat | Mitigation |
|--------|-----------|
| Character escalates own tools | `AllowlistToolExecutor` blocks calls outside grant |
| Character grants tools to specialist via handoff | Handoff grant capped by target's standing tools; audit log |
| Agent calls PATCH /tools on itself | Endpoint is operator-only (caller scope check) |
| Prompt injection enables tools | Tool policy is runtime-enforced, not prompt-based |
| Race condition on type change | Optimistic locking (`expected_revision`) + session restart |
| Tool toggle during active turn | Change takes effect on next turn |

### 6.2 Enforcement Points

```
┌─────────────────────────────────────────┐
│  UI (AppleApp.tsx)                      │  ← Tool toggles, personality picker
│  ↓ Validates but does NOT enforce       │
├─────────────────────────────────────────┤
│  Gateway API (server.py)                │  ← PATCH routes check operator scope
│  ↓ Loads policy from registry           │
├─────────────────────────────────────────┤
│  Agent Registry (types.py, specialists) │  ← effective_tools() computes allowlist
│  ↓ Passes to runtime                    │
├─────────────────────────────────────────┤
│  Runtime (tool_executor.py)             │  ← AllowlistToolExecutor ENFORCES
│  ↓ Blocks calls outside grant           │    ← This is the security boundary
└─────────────────────────────────────────┘
```

### 6.3 Operator-Only Operations

```python
# jaeger_ai/core/gateway/server.py

OPERATOR_ONLY_ROUTES = {
    "/v1/agents/{id}/tools",      # Tool toggle
    "/v1/agents/{id}/role",       # Role change
    "/v1/agents/{id}/personality", # Personality change
    "/v1/agents/pins",            # Pin management
    "/v1/agents/primary",         # Primary selection
}

async def require_operator(request: web.Request) -> None:
    """Only the operator (not agents, not external callers) can modify agent config."""
    caller = request.get("caller")
    if caller not in ("menubar", "cli", "webui", "ide"):
        raise web.HTTPForbidden(text="Agent configuration is operator-only")
```

---

## Part 7: Migration Strategy (V2)

### 7.1 Registry Version Bump

```python
# jaeger_ai/core/agent_registry/registry.py

REGISTRY_VERSION = 2  # Was 1

def migrate_registry_v1_to_v2(data: dict) -> dict:
    """Migrate existing agents to V2 (role + personality split)."""
    agents = data.get("agents", {})
    for agent_id, agent in agents.items():
        # V1: role was LEAD | SPECIALIST | RUNTIME
        # V2: add CHARACTER role + personality field
        
        role = agent.get("role", "specialist")
        
        # Explicit markers for migration
        if "character_template" in agent.get("metadata", {}):
            # Was created from character library → CHARACTER role
            agent["role"] = "character"
            agent.setdefault("metadata", {})["migrated_from_v1"] = True
        elif role == "lead":
            # Keep as LEAD
            agent["metadata"] = agent.get("metadata", {})
        else:
            # Default: SPECIALIST
            agent["role"] = "specialist"
    
    data["version"] = 2
    return data
```

### 7.2 Backward Compatibility

- **V1 agents** (no `personality` field) → treated as `personality = None`
- **V1 characters** (created from old `/from-template`) → get `role = "character"` on migration
- **V1 pins** → unchanged (localStorage + server pins both still work)
- **V1 primary** → unchanged (server-side `agent_primary` key)

---

## Part 8: Implementation Phases (V2 — Revised)

### Phase 1: Backend — Role System & Security (Week 1)

**Tasks:**
1. Add `AgentRole.CHARACTER` to enum
2. Add `CharacterPersonality` dataclass
3. Add `effective_tools()` function
4. Wire `AllowlistToolExecutor` to use `effective_tools()`
5. Add `PATCH /v1/agents/{id}/role` (with optimistic locking)
6. Add `PATCH /v1/agents/{id}/tools` (operator-only)
7. Add `PATCH /v1/agents/{id}/personality`
8. Registry migration (V1 → V2)
9. Unit tests for role system + security

**Deliverables:**
- [ ] `AgentRole.CHARACTER` exists and is validated
- [ ] Characters default to `tools=[]` (enforced)
- [ ] Tool toggle API works and is operator-only
- [ ] Role change requires session restart
- [ ] 20+ unit tests passing

### Phase 2: Sidebar — Grok Features (Week 2)

**Tasks:**
1. Pinned strip (supervisor tile + pinned agents)
2. Context menus (right-click, role-aware)
3. Unread indicators
4. ⌘K search palette
5. Avatar life states (idle/thinking/working/streaming)
6. Sections/grouping (Specialists vs Characters)
7. Character card thumbnails in rows

**Deliverables:**
- [ ] Pin/unpin with drag-and-drop
- [ ] Context menu shows correct items per role
- [ ] ⌘K opens search with agents + actions
- [ ] Character rows show card thumbnails
- [ ] Unread dots work

### Phase 3: Character System (Week 3)

**Tasks:**
1. Character card display (sidebar thumbnail + full modal)
2. Character creation from gallery
3. Tool toggle UI (per-character)
4. Personality display (traits, voice, quotes)
5. "Wear personality" for Lead/Specialists
6. Character editing (custom traits)

**Deliverables:**
- [ ] 20 character cards display correctly
- [ ] Characters created with tools off
- [ ] Tool toggles work and persist
- [ ] Lead can wear Jarvis personality
- [ ] Personality traits are visible/editable

### Phase 4: Polish & Testing (Week 4)

**Tasks:**
1. Animations (pin/unpin, context menu, avatar states)
2. Mobile responsive (long-press menus, swipe)
3. Accessibility (keyboard nav, screen readers)
4. Performance (virtual scrolling for 50+ agents)
5. E2E tests (Playwright)
6. Documentation

**Deliverables:**
- [ ] 60fps animations
- [ ] Mobile works
- [ ] WCAG 2.1 AA
- [ ] 100+ tests passing
- [ ] Lighthouse 95+

---

## Part 9: Comparison Table (Final)

| Feature | V1 Plan | V2 Plan | Industry Best |
|---------|---------|---------|---------------|
| **Agent types** | New `AgentType` enum | Extend `AgentRole` | Codex: TOML roles |
| **Pin vs Primary** | Conflated | Clear separation | Grok: Same separation |
| **Tool policy** | Advisory metadata | Enforced allowlist | Codex: Feature toggles |
| **Personality** | Mutually exclusive with role | Orthogonal (any agent can have) | Grok: Model-side only |
| **Character cards** | Gradient + emoji | Real card.png thumbnails | Unique to Jaeger |
| **Handoffs** | Not addressed | Capped by target's tools + audit | Codex: spawn_agent |
| **Migration** | Heuristic | Explicit markers + version | N/A |
| **Security** | Not specified | Operator-only + runtime enforcement | Codex: Inherited sandbox |

---

## Part 10: Open Questions (Resolved)

| Question | V1 Answer | V2 Answer |
|----------|-----------|-----------|
| Can characters use tools? | "Disabled by default" | **Enforced empty allowlist** — character CAN have tools if operator enables them |
| Can character BE specialist? | "No, keep distinct" | **Yes!** Role + personality are orthogonal. GLaDOS can be a sarcastic reviewer |
| Can Lead wear a character? | "Yes" | **Yes**, and ANY agent can have a personality overlay |
| How to show character voice? | Not addressed | Voice orb animates when character is "speaking" |
| Separate chat histories? | "Yes" | **Yes** — sessions are per-agent, sidebar groups by role |
| Pin vs Primary? | Conflated | **PIN = favorites (8 max), PRIMARY = identity (1 only), LEAD = execution role** |
| What about 50+ agents? | Virtual scrolling mentioned | **Virtual scrolling + API pagination + lazy card loading** |
| How to find agents? | ⌘K palette | **⌘K with fuzzy search + recent + quick actions** |
| Character templates updatable? | Not addressed | **Version tracking** — `personality_version` in metadata |
| Can agents share configs? | Not addressed | **Future:** Export/import character YAML |

---

## Approval Checklist

Before I start building, please confirm:

- [ ] **AgentRole.CHARACTER** (not new AgentType) — correct?
- [ ] **PIN ≠ PRIMARY ≠ LEAD** — three separate concepts — correct?
- [ ] **Role + Personality orthogonal** — any agent can have personality — correct?
- [ ] **Tool policy enforced at runtime** (AllowlistToolExecutor) — secure enough?
- [ ] **Phase 1 first** (backend) — then Phase 2 (sidebar) — correct order?
- [ ] **Real character cards** (card.png) in sidebar — yes?
- [ ] **Grok features**: Pinning, context menu, ⌘K, unread, avatar states — all wanted?
- [ ] **4-week timeline** — reasonable?

---

*V2 Plan — Audited and Revised — 2026-10-26*
