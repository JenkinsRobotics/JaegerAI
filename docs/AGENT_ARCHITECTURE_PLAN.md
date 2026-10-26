# Agent Architecture & Sidebar Enhancement Plan

**Date:** 2026-10-26
**Status:** Planning Phase — Awaiting Approval
**Author:** GitHub Copilot

---

## Executive Summary

We need to **rebuild the sidebar** to properly support **two distinct agent types** with **Grok-inspired features** layered on top of our **Apple-native design**:

1. **Specialists** — Subject matter experts (coders, researchers, reviewers) that use tools
2. **Characters** — Personality-driven personas (Jarvis, Lilith, Kamina) for roleplay/philosophy with minimal tools

The current Apple-native sidebar is beautiful but missing critical Grok features. The canonical sidebar has them but uses the old design. We need to **merge both**.

---

## Part 1: Agent Type Architecture

### 1.1 The Two Types

| Aspect | **Specialists** | **Characters** |
|--------|----------------|----------------|
| **Purpose** | Task completion, expert work | Personality, roleplay, philosophy |
| **Examples** | Builder, Reviewer, Researcher, Robotics Architect | Jarvis, Lilith, Kamina, GLaDOS, Bender |
| **Tool Use** | Heavy (code, files, shell, search) | Minimal (chat, maybe read-only) |
| **Personality** | Functional, professional | Rich (HEXACO, SPECIAL, Expression traits) |
| **Voice** | Neutral/professional | Distinct voice per character |
| **Card Art** | Placeholder/professional | Full character cards (320×420 PNG) |
| **Default State** | Tools enabled | Tools disabled by default |
| **Creation** | From scratch or standing specialists | From character template library |

### 1.2 Current Implementation Analysis

**Existing in codebase:**
- ✅ `AgentRole.LEAD` and `AgentRole.SPECIALIST` exist in `jaeger_ai/core/agent_registry/types.py`
- ✅ `STANDING_SPECIALISTS` defined in `jaeger_ai/core/agent_registry/specialists.py`
- ✅ 20 character templates in `jaeger_ai/features/personality/characters/`
- ✅ Each character has: `character.yaml`, `card.png`, `lore/`, `SOUL.md`
- ✅ Character traits: HEXACO, SPECIAL, Expression, Domains

**Missing/Gaps:**
- ❌ No `AgentRole.CHARACTER` type — characters and specialists are conflated
- ❌ No tool toggle system for characters (they inherit everything)
- ❌ Character cards not properly displayed (only in new CharacterGallery)
- ❌ No distinction in sidebar UI between the two types
- ❌ Character creation doesn't set up personality properly

### 1.3 Proposed Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Registry                        │
├─────────────────────────────────────────────────────────┤
│  LEAD (Primary)                                         │
│  └── The main Jaeger companion (can wear a character)   │
├─────────────────────────────────────────────────────────┤
│  SPECIALISTS (Task Experts)                             │
│  ├── Builder — writes code, runs builds                 │
│  ├── Reviewer — code review, testing                    │
│  ├── Researcher — papers, docs, analysis                │
│  ├── Robotics Architect — hardware, embedded            │
│  ├── Reliability Auditor — security, testing            │
│  ├── Research Strategist — synthesis, trade-offs        │
│  ├── Systems Principal — architecture, design           │
│  └── [Custom specialists...]                            │
├─────────────────────────────────────────────────────────┤
│  CHARACTERS (Personas)                                  │
│  ├── Jarvis — British butler (tools: read-only)         │
│  ├── Lilith — Self-aware AI (tools: none)               │
│  ├── Kamina — Motivational leader (tools: none)         │
│  ├── GLaDOS — Test AI (tools: read-only)                 │
│  ├── Bender — Sarcastic robot (tools: none)             │
│  └── [Custom characters from library...]                │
└─────────────────────────────────────────────────────────┘
```

### 1.4 Database/API Changes

**New Agent Type:**
```python
# jaeger_ai/core/agent_registry/types.py
class AgentType(str, Enum):
    LEAD = "lead"           # Primary companion
    SPECIALIST = "specialist"  # Task expert (tools enabled)
    CHARACTER = "character"    # Persona (tools disabled by default)
```

**Agent Record Extensions:**
```python
# In agent metadata:
{
    "agent_type": "specialist" | "character" | "lead",
    "character_template": "jarvis",  # If from character library
    "personality": {
        "traits": {...},  # HEXACO/SPECIAL/Expression
        "voice_id": "bm_george",
        "voice_tone": "crisp, dry, British-butler",
        "backstory": "...",
        "soul": "...",
    },
    "tool_policy": {
        "enabled": ["read_file", "search_files"],  # Explicit allowlist
        "disabled_by_default": True,  # For characters
    },
    "card_url": "/v1/characters/jarvis/card",
}
```

**New API Endpoints:**
```
GET  /v1/characters              — List character templates (existing)
GET  /v1/characters/{id}         — Get character details (existing)
GET  /v1/characters/{id}/card    — Serve card.png (existing)
POST /v1/agents/from-character   — Create character agent (NEW)
POST /v1/agents/from-specialist  — Create specialist agent (NEW)
PATCH /v1/agents/{id}/type       — Change agent type (NEW)
PATCH /v1/agents/{id}/tools      — Toggle tools for agent (NEW)
```

---

## Part 2: Sidebar Feature Matrix

### 2.1 Grok Features to Port (from canonical sidebar)

| # | Feature | Priority | Effort | Current Apple UI | Canonical Source |
|---|---------|----------|--------|------------------|------------------|
| 1 | **Pinning agents** (drag-to-pin) | 🔴 High | 4h | ❌ Missing | `PinnedArea.tsx`, `pins.ts` |
| 2 | **Context menu** (right-click) | 🔴 High | 6h | ❌ Missing | `AgentContextMenu.tsx` |
| 3 | **Unread indicators** | 🔴 High | 2h | ❌ Missing | `unread.ts`, `AgentRow.tsx` |
| 4 | **Avatar life states** | 🟡 Medium | 8h | ❌ Missing | `avatarMotion.ts`, `AgentAvatar.tsx` |
| 5 | **Sections/grouping** | 🟡 Medium | 4h | ❌ Missing | `sections.ts` |
| 6 | **⌘K Search palette** | 🔴 High | 4h | ❌ Missing | `JumpTo.tsx` |
| 7 | **Star badge (primary)** | 🟡 Medium | 1h | ✅ Has | `AgentAvatar.tsx` |
| 8 | **Chat list under agent** | 🟢 Low | 6h | ❌ Missing | `ChatList.tsx` |
| 9 | **New Chat menu (+)** | 🟡 Medium | 2h | ✅ Has (simple) | `NewChatMenu.tsx` |
| 10 | **Agent details panel** | 🟢 Low | 4h | ❌ Missing | `AgentDetails.tsx` |
| 11 | **Template system** | 🟢 Low | 4h | ❌ Missing | `TemplateCatalog.tsx` |
| 12 | **Resizable sidebar** | 🟢 Low | 2h | ✅ Has (collapse) | `AppShell.tsx` |
| 13 | **Agent type badges** | 🔴 High | 1h | ❌ Missing | NEW for characters |
| 14 | **Character card preview** | 🔴 High | 4h | ⚠️ Partial | NEW from character lib |
| 15 | **Tool toggle per agent** | 🔴 High | 4h | ❌ Missing | NEW for characters |

### 2.2 Apple-Native Features to Keep

| Feature | Keep? | Notes |
|---------|-------|-------|
| SF Pro typography | ✅ Yes | Apple-native feel |
| System colors | ✅ Yes | Light/dark mode |
| Smooth animations | ✅ Yes | 60fps transitions |
| Mobile responsive | ✅ Yes | Hamburger menu |
| Voice orb | ✅ Yes | Unique to our UI |
| ChatGPT-style messages | ✅ Yes | Main chat area |
| Gradient agent avatars | ✅ Yes | Enhanced with character art |

### 2.3 Visual Design: Merged Sidebar

```
┌──────────────────────────────────────────────┐
│  🔍 Search... (⌘K)              [≡] [+]      │  ← Header
├──────────────────────────────────────────────┤
│                                              │
│  ⭐ PINNED (2)                                │  ← Pinned section
│  ┌────┐ ┌────┐ ┌────┐                       │
│  │ 🎩 │ │ 🔮 │ │ 🔥 │  Jarvis Lilith Kamina │  ← Pinned tiles
│  │Jarv│ │Lili│ │Kami│  (with unread dots)   │
│  └────┘ └────┘ └────┘                       │
│                                              │
│  👔 SPECIALISTS (5)              [+ Create]  │  ← Specialists section
│  ┌────────────────────────────────────┐     │
│  │ [🛠️] Builder          ●          │     │  ← Agent row
│  │      Code & implementation         │     │     (avatar, name, 
│  │      ─────────────────────────     │     │      status, unread)
│  ├────────────────────────────────────┤     │
│  │ [🔍] Researcher       ○          │     │
│  │      Papers & analysis             │     │
│  │      ─────────────────────────     │     │
│  ├────────────────────────────────────┤     │
│  │ [🔧] Robotics Arch.   ○          │     │
│  │      Hardware & embedded           │     │
│  └────────────────────────────────────┘     │
│                                              │
│  🎭 CHARACTERS (3)               [+ Create]  │  ← Characters section
│  ┌────────────────────────────────────┐     │
│  │ [🎩] Jarvis           ● ○○ Tools  │     │  ← Character row
│  │      AI Butler                     │     │     (card thumb, name,
│  │      "I've taken the liberty..."   │     │      role, tool toggle)
│  │      ─────────────────────────     │     │
│  ├────────────────────────────────────┤     │
│  │ [🔮] Lilith           ○ ⚪ Tools  │     │
│  │      Self-aware AI                 │     │
│  │      "I prefer not to guess..."    │     │
│  └────────────────────────────────────┘     │
│                                              │
├──────────────────────────────────────────────┤
│  [👤] Operator          [⚙️] [🔍] [💬]       │  ← Footer
└──────────────────────────────────────────────┘
        ↑ Drag to reorder, right-click for menu
```

---

## Part 3: Implementation Phases

### Phase 1: Backend — Agent Type System (Week 1)

**Goal:** Distinguish specialists from characters at the data level.

**Tasks:**
1. Add `AgentType.CHARACTER` to `types.py`
2. Add `character_template`, `personality`, `tool_policy` to agent metadata
3. Create specialist/character factory functions
4. Add tool toggle API (`PATCH /v1/agents/{id}/tools`)
5. Add type change API (`PATCH /v1/agents/{id}/type`)
6. Update character routes to properly create character agents
7. Write unit tests for type system

**Files to modify:**
- `jaeger_ai/core/agent_registry/types.py` — Add `AgentType.CHARACTER`
- `jaeger_ai/core/agent_registry/specialists.py` — Add character factory
- `jaeger_ai/core/gateway/character_routes.py` — Fix creation flow
- `jaeger_ai/core/gateway/server.py` — Add new endpoints

**Deliverables:**
- [ ] Characters can be created with tools disabled
- [ ] Specialists can be created with tool allowlists
- [ ] Type can be changed after creation
- [ ] 10+ unit tests passing

---

### Phase 2: Sidebar — Grok Features (Week 2)

**Goal:** Port Grok sidebar features to Apple-native design.

**Tasks:**
1. **Pinning system**
   - Add pinned section at top of sidebar
   - Drag agents to pin/unpin
   - Right-click → "Pin to top" / "Unpin"
   - Persist to localStorage

2. **Context menus**
   - Right-click agent → menu with:
     - Pin/Unpin
     - Mark as read
     - Rename
     - Change type (Specialist ↔ Character)
     - Toggle tools
     - Delete
   - Long-press on mobile

3. **Unread indicators**
   - Blue dot on agent rows
   - Blue dot on pinned tiles
   - Mark as read on click

4. **⌘K Search palette**
   - Overlay modal (not sidebar)
   - Search agents by name/role
   - Keyboard navigation
   - Quick actions

5. **Avatar life states**
   - Idle: gentle breathing
   - Thinking: pulse animation
   - Working: spin/rotate
   - Streaming: wave animation
   - Connect to Gateway events

6. **Sections/Grouping**
   - "Pinned" section (auto)
   - "Specialists" section
   - "Characters" section
   - Custom sections (drag to create)

**Files to create:**
- `jaeger_ai/interfaces/ui/src/components/PinnedAgents.tsx`
- `jaeger_ai/interfaces/ui/src/components/AgentContextMenu.tsx` (Apple-styled)
- `jaeger_ai/interfaces/ui/src/components/SearchPalette.tsx`
- `jaeger_ai/interfaces/ui/src/components/AvatarLifeStates.tsx`
- `jaeger_ai/interfaces/ui/src/lib/pins.ts` (port from canonical)

**Files to modify:**
- `jaeger_ai/interfaces/ui/src/AppleApp.tsx` — Integrate all features
- `jaeger_ai/interfaces/ui/src/theme/apple-app.css` — Add new styles

**Deliverables:**
- [ ] Agents can be pinned with drag-and-drop
- [ ] Right-click shows context menu
- [ ] Unread dots appear and clear
- [ ] ⌘K opens search palette
- [ ] Avatars animate based on state
- [ ] Sidebar shows specialists and characters in separate sections

---

### Phase 3: Character Cards & Personality (Week 3)

**Goal:** Display real character cards and enable personality-driven agents.

**Tasks:**
1. **Character card display**
   - Show card.png thumbnail in sidebar (32×42px)
   - Full card in detail modal (320×420px)
   - Fallback to gradient + emoji if no card

2. **Character creation flow**
   - "Create Agent" → Choose "Character" tab
   - Browse character library (20 templates)
   - Preview card, traits, backstory
   - Create with:
     - Tools disabled by default
     - Voice configured
     - Personality loaded

3. **Tool toggle UI**
   - In character detail panel
   - Toggle individual tools on/off
   - "Enable all" / "Disable all" buttons
   - Visual indicator of tool count

4. **Personality display**
   - Show top traits as bars
   - Show voice tone
   - Show signature quotes
   - Show backstory snippet

**Files to create:**
- `jaeger_ai/interfaces/ui/src/components/CharacterCard.tsx` — Card display
- `jaeger_ai/interfaces/ui/src/components/ToolToggle.tsx` — Tool switches
- `jaeger_ai/interfaces/ui/src/components/PersonalityDisplay.tsx` — Trait bars

**Files to modify:**
- `jaeger_ai/interfaces/ui/src/components/CharacterGallery.tsx` — Add "Character" vs "Specialist" tabs
- `jaeger_ai/interfaces/ui/src/components/CreateAgentModal.tsx` — Two creation flows

**Deliverables:**
- [ ] Character cards display in sidebar
- [ ] Full card view in modal
- [ ] Characters created with tools off
- [ ] Tool toggles work per-agent
- [ ] Personality traits visible

---

### Phase 4: Polish & Testing (Week 4)

**Goal:** Production-ready sidebar with full test coverage.

**Tasks:**
1. **Animations & transitions**
   - Smooth pin/unpin animations
   - Context menu fade-in
   - Avatar state transitions
   - Search palette slide-in

2. **Mobile responsive**
   - Long-press instead of right-click
   - Swipe actions
   - Touch-friendly targets (44px)

3. **Accessibility**
   - Keyboard navigation
   - Screen reader labels
   - Focus indicators
   - Reduced motion support

4. **Testing**
   - Unit tests for all new components
   - E2E tests for pinning, context menu, search
   - Visual regression tests
   - Performance benchmarks

**Deliverables:**
- [ ] All animations smooth (60fps)
- [ ] Mobile works perfectly
- [ ] WCAG 2.1 AA compliant
- [ ] 50+ new tests passing
- [ ] Lighthouse score 95+

---

## Part 4: Detailed Recommendations

### 4.1 Agent Type Defaults

| Creation Method | Default Type | Default Tools | Default Personality |
|-----------------|--------------|---------------|-------------------|
| From character template | `character` | None (disabled) | Full (from YAML) |
| From specialist template | `specialist` | Read + write + shell | None (functional) |
| Custom creation | `specialist` | Configurable | None |
| Standing specialist | `specialist` | Per-definition | None |

### 4.2 Character Tool Policy

**Recommended default tool sets for characters:**

| Character Type | Suggested Tools | Rationale |
|----------------|-----------------|-----------|
| **Conversational** (Jarvis, Lilith, Kamina) | None | Pure personality |
| **Creative** (Bender, GLaDOS, Mochi) | `write_file` (notes only) | Save creative output |
| **Analytical** (HAL 9000, TARS) | `read_file`, `search_files` | Read-only research |
| **Custom** | User choice | Toggle per agent |

### 4.3 Sidebar Section Order

1. **Pinned** — User's favorites (drag here)
2. **Lead Agent** — The primary Jaeger (always visible)
3. **Specialists** — Task experts (collapsible)
4. **Characters** — Personas (collapsible)
5. **Archived** — Hidden agents (collapsed, at bottom)

### 4.4 Character Card Integration

**Sidebar row (compact):**
```
┌───┐  Jarvis                    ●
│ 🎩│  AI Butler            [2 tools]
│32 │  "I've taken the liberty…"
│ × │
│42 │
└───┘
```

**Detail modal (full):**
```
┌─────────────────────────┐
│  ┌─────────┐            │
│  │         │  Jarvis     │
│  │  CARD   │  AI Butler  │
│  │  320×420│             │
│  │         │  ─────────  │
│  │         │  Traits:    │
│  │         │  ▓▓▓▓▓▓░░ Intelligence 95%│
│  │         │  ▓▓▓▓▓▓░░ Conscientious 95%│
│  │         │  ▓▓▓▓▓░░░ Warmth 70%    │
│  │         │             │
│  │         │  Voice:     │
│  │         │  crisp, dry, British │
│  │         │             │
│  │         │  [Tools (2)]│
│  │         │  ☑ read_file│
│  │         │  ☑ search   │
│  │         │  ☐ write    │
│  │         │  ☐ shell    │
│  └─────────┘            │
│  [Start Chat] [Edit]    │
└─────────────────────────┘
```

### 4.5 Migration Path

**Existing agents:**
1. Scan all agents on startup
2. If agent has `character_template` in metadata → type = `character`
3. If agent name matches standing specialist → type = `specialist`
4. If agent has `role: lead` → type = `lead`
5. Default → `specialist`

**Existing characters:**
1. The 20 character templates remain unchanged
2. New agents created from them get proper type
3. Old agents can be converted via context menu

---

## Part 5: File-by-File Change Plan

### Backend (Python)

| File | Changes | Lines |
|------|---------|-------|
| `jaeger_ai/core/agent_registry/types.py` | Add `AgentType.CHARACTER` | +10 |
| `jaeger_ai/core/agent_registry/specialists.py` | Add character factory, tool policies | +100 |
| `jaeger_ai/core/gateway/character_routes.py` | Fix creation, add tool toggle | +150 |
| `jaeger_ai/core/gateway/server.py` | Add new endpoints | +50 |
| `jaeger_ai/core/gateway/agent_routes.py` | Add type change endpoint | +80 |

### Frontend (React/TypeScript)

| File | Changes | Lines |
|------|---------|-------|
| `src/components/PinnedAgents.tsx` | NEW — Pinned section | +200 |
| `src/components/AgentContextMenu.tsx` | NEW — Right-click menu (Apple-styled) | +300 |
| `src/components/SearchPalette.tsx` | NEW — ⌘K search overlay | +250 |
| `src/components/AvatarLifeStates.tsx` | NEW — Animated avatars | +200 |
| `src/components/CharacterCard.tsx` | NEW — Card display component | +150 |
| `src/components/ToolToggle.tsx` | NEW — Tool switches | +100 |
| `src/components/PersonalityDisplay.tsx` | NEW — Trait bars | +100 |
| `src/lib/pins.ts` | NEW — Pin management | +80 |
| `src/lib/agentTypes.ts` | NEW — Type utilities | +50 |
| `src/AppleApp.tsx` | Major update — integrate all | +400 |
| `src/theme/apple-app.css` | Major update — new styles | +500 |

### Tests

| File | Changes |
|------|---------|
| `dev/tests/unit/python/test_agent_types.py` | NEW — Type system tests |
| `src/components/__tests__/PinnedAgents.test.tsx` | NEW |
| `src/components/__tests__/AgentContextMenu.test.tsx` | NEW |
| `src/components/__tests__/SearchPalette.test.tsx` | NEW |
| `src/components/__tests__/CharacterCard.test.tsx` | NEW |
| `tests/e2e/sidebar.spec.ts` | NEW — E2E tests |

---

## Part 6: Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Agent types distinguished | 100% | 0% |
| Character cards displayed | 20/20 | 0/20 |
| Grok features ported | 10/15 | 2/15 |
| Tool toggle per character | Yes | No |
| Sidebar load time | <100ms | ~50ms |
| Test coverage (new code) | 80% | 0% |
| User can create character in | <30s | N/A |

---

## Part 7: Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing agents | High | Migration script, backward compat |
| Character tools enabled by accident | Medium | Default off, explicit toggle |
| Performance with many agents | Medium | Virtual scrolling, lazy load |
| Mobile UX complexity | Medium | Long-press menus, swipe actions |
| Character personality too strong | Low | Tool policy enforced at runtime |

---

## Part 8: Timeline

```
Week 1: ████████ Backend — Agent Type System
Week 2: ████████ Sidebar — Grok Features (Pinning, Menus, Search)
Week 3: ████████ Characters — Cards, Personality, Tool Toggles
Week 4: ████████ Polish — Animations, Mobile, Tests, Docs
```

**Total Effort:** ~160 hours (4 weeks, 1 developer)

---

## Part 9: Open Questions

1. **Should characters be able to use ANY tools, or hard-limited?**
   - Recommendation: Soft limit — tools disabled by default, user can enable

2. **Can a character BE a specialist?**
   - Recommendation: No — keep types distinct. A character agent is conversational; a specialist agent is functional.

3. **Should the Lead agent be able to "wear" a character?**
   - Recommendation: Yes — Lead can have a character overlay (personality) while keeping tool access

4. **How to handle character voice in the UI?**
   - Recommendation: Show voice orb animation when character is "speaking", use voice_id for TTS

5. **Should characters have their own chat history separate from specialists?**
   - Recommendation: Yes — separate sessions per agent, filtered by type in sidebar

---

## Approval

**Status:** ⏳ Awaiting user approval

**Next Step:** Review this plan, answer open questions, then begin Phase 1.

---

*Plan created: 2026-10-26*
*JaegerAI — Agent Architecture & Sidebar Enhancement*
