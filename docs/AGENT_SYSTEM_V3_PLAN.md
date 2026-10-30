# JaegerAI Agent System v3 — Clean Architecture Plan

> **Apple approach: clarify, reduce, perfect. One concept per word. No aliases.**

---

## 1. Audit: What's Wrong With the Current Dashboard

### The "Lead Active" Mess

The dashboard had `activeLead: Agent` + `Lead Agents` section. What did that mean?

- **Is there always a lead?** Yes, but who? The backend has `native:jaeger` and the frontend mocks `jaeger-main`. Both claim to be "the lead."
- **Can you have multiple leads?** The AgentRole allows `LEAD` on any agent, but the sidebar header says "Lead Agents" then shows only one (if `isPrimary`). The next-most-important label should be unambiguous.
- **Active vs. Primary:** We used `activeAgent` (which chat is open), `isPrimary` (star badge), `isOnline` (green dot), and `isPinned` (pinned strip) as four separate booleans. Three of them were doing overlapping jobs.

**Apple would fix this by giving each concept one name and one owner:**

| Concept | Owner | Canonical Name | Allowed Values | Visual |
|---|---|---|---|---|
| **Who you are talking to** | Frontend state | **Active** | One agent or null | Blue highlight row |
| **Who runs point for a project** | Project record | **Lead** | One per project, nullable (you pick) | 👑 badge in project card |
| **Saved for quick access** | localStorage | **Pinned** | 0–8 | Top strip |
| **Primary persona** | `instance.yaml` | **Persona** | One character ID | Not in sidebar at all |
| **Health** | Poll | **Status** | `online` / `away` | Green/gray dot |

Rules:

- **Active** is transient UI state. It is not stored on any record.
- **Lead** is scoped to a **project**, not to the sidebar. A global "lead" outside a project means nothing — every new user should be staring at an empty state, not a fake team of 7.
- **Pinned** is a shortcut. It should not decide who is the lead.
- **Primary/Persona** is the operator's default voice for *new* work. It belongs in Settings → Persona, not in the agent list.

### Missing: The Project as a First-Class Object

The dashboard showed `activeLead` with a percent complete — but where was the **project** underneath? Without a `Project` record there is no progress to track, no assignees to show, and no place to reset the system cleanly.

---

## 2. Target Architecture

```
Operator
   │
   └── Persona (one Character, e.g. "assistant")
          │
          ├── Project 1 ── { title, team, created_at, status }
          │     ├── Chat thread (conversation)
          │     ├── Kanban board (tasks, board.json lives here)
          │     └── Lead: one agent the operator chose to "run point"
          │
          ├── Project 2
          │     └── ...
          │
          └── Inbox — unassigned pings from other surfaces
                    (not a project, just "hey look here")
```

What goes away:

- `isPrimary` / primary star (replaced by Persona in Settings)
- `activeLead` dashboard hero (replaced by Project cards with Lead badges)
- Duplicated `agentType` (redundant with `role`; remove `agentType` entirely)

---

## 3. Agent Roles: Keep It to Three + One Persona

| Role | Meaning | Can have tools | Example |
|---|---|---|---|
| `lead` | Runs point on a project | Yes (via project permission) | The agent you choose when you start a project |
| `specialist` | Domain expert, tool-heavy | Yes (allowlist) | Builder, Reviewer, Auditor |
| `character` | Voice/personality skin | No by default (opt-in per-agent) | Jarvis, Lilith, Kamina |
| — | Persona | One character worn by the **operator**, not an agent | The "you" of new work |

A specialist **can wear** a character (e.g. "GLaDOS the reviewer"). That is stored as `personality` on the `AgentRecord` and rendered as a combined prompt — no extra enum needed. This keeps the role set stable.

Backend is already correct (`types.py: AgentRole` + `CharacterPersonality`, `specialists.py: effective_tools()`). No change there. Changes are:
- Remove `agentType` alias from frontend (use `role` only).
- Stop fabricating a 7-agent default team.

---

## 4. Reset: New Customer Starts Empty

For a new customer "build them fresh" means: **empty roster, empty projects**.

Default state after `setup` (one line in `setup_wizard.py`):

```python
# Post-setup: one Lead-equivalent agent, no character, no specialists, no projects.
# Persona = assistant (neutral). Agent registry = [builtin: lead template, inactive].
```

Mock data for `?ui=apple` must match:

```js
// AppleApp.tsx — what a brand-new operator actually sees
useMockData() → {
  agents: [],            // "Your team is empty"
  pinned: [],
  projects: [],         // "Start your first project"
  persona: "assistant", // Settings → Persona shows the neutral sheet
}
```

And the sidebar renders **empty states**, not fake agents:

- **Agents section:** `No agents yet — create one from a character or a specialist.`
- **Pinned strip:** hidden when there is no lead.
- **Dashboard:** `No projects yet — start one.`

Migration: if an existing operator already has agents, those agents stay. The empty default only applies at creation time (checked by `instance_root.is_new()` or "first_boot without standing specialists").

---

## 5. Dashboard: What It Is

**Dashboard = the operator's HQ. It answers: what needs my attention now?**

Information hierarchy (top to bottom):

1. **Active Projects** — the operator approved this. **This you called out as the one keeper.**
   - Card per project: title, short team summary (e.g. "Lead: Jarvis · Builder, Researcher"), **percent complete from Kanban columns**, **CTA [View] [Assign] [Review]**.
   - Progress comes from `board.json` columns: `done / total`. No fake percentages.
   - Tap a card → project workspace (chat + board).

2. **Empty states, not fake data.** When `projects.length === 0`, the "Active Projects" area says:
   > `You haven't started a project yet.
   >  Give your lead a job — agents join when you assign them.`

3. **Inbox (optional, second section).** One row: unread handoff notices or system pings. This is the only place unread counts make sense for an operator-as-manager. Not per-agent dots pretending you are a messaging app.

What goes **away** from the dashboard:

- Big `Lead / Working / Done` number tiles with no source (no numbers without provenance).
- "Your team" roster duplicate (that lives in **Agents**).
- "Assign Work" input on the dashboard (that belongs on **Agents → Create → pick team → new project**, so the decision of "which agents" precedes "do it").

**The dashboard never shows an "active lead" in isolation.** A lead without a project answering it is a meaningless status light.

---

## 6. Information Flow

```
Dashboard         ⇄ Project records (progress, team)
   ↓ tap / Create
Agents page       ⇄ Agent registry (+ Character library as a "source" for new agents)
   ↓ "Create specialist" / "Create from character"
Project Detail    ⇄ Kanban board (columns: backlog/todo/doing/done)
   ↓ chat
Chat thread       ⇄ Conversations scoped to the active project
```

- The **Agents** page owns creation and the Pinned strip. It has two sections when there is state: **Pinned → Specialists → Characters (collapsed by default)**. When there is no state, it shows a single CTA: `Create from a character`.
- The **Chat** is the lead's thread **inside a project** when a project exists. Outside a project, it is the operator's persona chat (not an agent chat).

---

## 7. Implementation Phases

### Phase A — Correct the data (no UI regression)

- [x] Backend: `AgentRole.CHARACTER` + `CharacterPersonality` + `effective_tools()` + V2 routes — done (`test_agent_v2.py` green).
- [ ] Remove the fake 7-agent mock roster in `AppleApp.tsx`. Return to **empty default** with dedicated `useAgentStore()` that starts empty and loads from Gateway (fallback: empty, not fabricated).
- [ ] Remove `agentType` from frontend `Agent` (one field: `role`).
- [ ] Add `Project` + `KanbanBoard` types in `types.ts` (local-only for now; Gateway-owned later).
- [ ] Add a **Persona** picker in Settings (wraps `instance.character_id`), not an `isPrimary` star in the sidebar.

### Phase B — Ship the manager UX

- [ ] `DashboardPage.tsx` — two-state component: empty (`no projects`) or active-project cards with real progress. No fake numbers.
- [ ] `AgentsPage.tsx` — roster + pinned strip. Characters are a **source** for "Create specialist: from character".
- [ ] `ProjectDetailPage.tsx` — chat + board columns, header shows the project's **Lead**.
- [ ] Move `Create Agent Modal` → `AgentsPage`; remove the always-visible "Create Agent" banner from the sidebar (replaced by + inside each grouped header on Agents page only).

### Phase C — Wire the runtime

- [ ] Persist projects and kanban to storage (start with `~/.jaeger/workspace/`; Gateway owns in a later cut, feature-flagged with `useProjectStore`).
- [ ] Project "View" opens its board; "Assign" opens the team picker; "Review" jumps to approvals.
- [ ] Unify `isOnline` terminology to `status` (`online`/`away` — single boolean `isOnline` or single string, not both).

### Phase D — Polish

- [ ] Audit every agent dot/count/badge against one truth: unread comes from **project activity**, not a per-agent counter.
- [ ] Tests: 5 dashboard states (empty, one project with/without team, with progress, with unread), agent creation from character, pin/unpin.
- [ ] Docs: update `ARCHITECTURE_V2_PLAN` → `docs/agent-v3/`

---

## 8. Questions Before You Build (Answer in One Line Each)

1. **Lead assignment:** Do you want to pick the project Lead at **creation time**, or **later** from the project detail page?
2. **Kanban source of truth now:** Ship a local `board.json` under `~/.jaeger/workspace/projects/<id>/` first, then promote to Gateway, or wait for Gateway-owned projects before showing Active Projects at all?
3. **Character persona vs. character agent:** Should "Browse Characters" create an **agent** (V2 behavior) or change your **Persona** (operator default voice)?
4. **Mochi/Jarvis default:** Stay truly empty (no prebuilt agents), or ship with **one invisible default lead** that only appears after the first project?

---

## 9. Definition of Done for This Reset

- A fresh operator sees: Dashboard (active projects, no projects state), Agents (empty with CTA), Settings → Persona (Assistant), Chat (empty with a prompt to start a project).
- The 20 characters remain browsable in the Character Library page, but **no agents exist until you create one**.
- `activeLead`, `isPrimary` star, and the fake team disappear from code. `lead` is a per-project field. `pinned` stays. `persona` lives in Settings.
- All existing 63 backend tests green; new frontend tests for Dashboard empty/active states.

