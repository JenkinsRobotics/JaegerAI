# Product sprint status — 2026-09-11 ~09:45 PT

**Machine:** MatthewacStudio (`f9644398-ff83-41bc-94e8-7d0bca7aac5d`)  
**Branch:** `finish-alpha` @ `975b6b2` (ahead of origin; not pushed)  
**Repo only:** `/Users/matthewjenkins/GitHub/JaegerAI`  
**Claim level:** Grok-**shaped** start — **do not** claim more-advanced-than-Grok yet (handoffs are stubs; no proven live multi-agent turn).

Also written to box: `/workspace/product-sprint-status.md`.

## Locked IPs (still)

| Role | URL |
|------|-----|
| Ollama | `http://192.168.64.1:11434` |
| WebUI | `http://100.74.2.15:8790/` |
| Gateway | `http://127.0.0.1:8810` |

Spine M1–M10 already green ×2 (prior). This sprint = product bar P1–P8.

## What landed

### 1. Unified Mac + WebUI shell
- Shared tokens/docs: `docs/shell-tokens.md` (brand, Chat/Agents/Settings nav parity, catalog contract).
- WebUI branding extension: Jaeger title chrome, hide Todos + Hermes dashboard, inject **Agents** list from `/api/agents` (activate on click).
- Mac `ChatView`: Gateway catalog dedupe, default `native:jaeger`, **activate on row click**, specialist tint (Surfaces/Gateway/Everyday cyan).
- Evidence: Gateway IDs == WebUI `/api/agents` IDs (exact match, 8 agents incl. specialists).

### 2. UI bugs / GUI testing
- Todos rail remains hidden (no `/api/todos` — 404).
- **GUI AX blocked:** `osascript` → `AX_ERROR -1728: osascript is not allowed assistive access.`
  - **Matthew must grant:** System Settings → Privacy & Security → **Accessibility** for Cursor and/or Terminal. Optional: **Screen Recording**.
  - Continued with API-level + HTTP probes; `swift build -c release --product JaegerAI` PASS.

### 3. Grok-shaped product (lead + specialists + handoff stub)
- Standing specialists in AgentRegistry:
  - Lead: `native:jaeger` / **Assistant** (`role=lead`)
  - `native:surfaces` / Surfaces
  - `native:gateway` / Gateway
  - `native:everyday` / Everyday
- Handoff stub: `POST /v1/agents/{id}/handoff` + approvals via `POST /v1/approvals/{id}` (approve + deny proven).
- Tool: `call_agent(...)` → Gateway handoff (`stub: true`).
- WebUI proxy: `/api/agents/*/handoff` + `/api/handoffs`.

### 4. Commits (finish-alpha)
- `4aecd61` feat(surfaces): unify AGENTS catalog chrome on Mac + WebUI
- `82c9bab` feat(surfaces): WebUI Chat/Avatar/Work stage pills
- `975b6b2` feat(product): Grok-shaped lead + specialists with handoff stub
- Submodule `vendor/hermes-webui` handoff proxy `330d2ce4`

### 5. Honesty gate
**Not claimed:** live multi-agent specialist turn, surpassing Grok Bot, full AX GUI matrix.

## Product Must snapshot

| ID | Status | Evidence |
|----|--------|----------|
| P1 same catalog | **GREEN** | ID lists match (8 agents) |
| P2 shared chrome | **YELLOW→GREEN-ish** | Branding + tokens; screenshots TCC-blocked |
| P3 WebUI turn | **YELLOW** | Catalog/activate/handoff API OK |
| P4 Mac happy path | **YELLOW** | swift build PASS; AX blocked |
| P5 no P0 UI bugs | **YELLOW** | Todos hidden; crons soft 503 residual |
| P6 handoff | **YELLOW (stub GREEN)** | Approve/deny on :8810; not live specialist turn |
| P7 specialists registered | **GREEN** | Registry + `/v1/agents` |
| P8 approval path | **GREEN (API)** | Deny + approve via `/v1/approvals/{id}` |


### 6. Gateway lead Ollama soft-fail SI prompt (SOUL)
- Lead soft-fail → Ollama system prompt now: `[Identity]` (`character_block`) then optional `[SOUL]` via `load_soul(InstanceLayout)` on the same `resolve_instance_dir` root.
- Empty / unreadable SOUL omitted (soft-fail). Specialist thin overlay unchanged. MCP native path unchanged. No costume/character rebinds. Provenance skipped.
- Unit: `test_lead_softfail_prompt_includes_soul`, `test_si_soul_prompt_uses_instance_layout`.

## Next
1. Grant Accessibility (+ Screen Recording) → Mac GUI matrix.
2. Wire UI approval card for handoff `approval.request`.
3. Replace handoff stub with real specialist turn before any “beyond Grok” claim.
4. Second product probe ≥30m later for P-Must ×2.

## TIP (SI continuity-approve)
- Gateway lead soft-fail prompt includes SOUL — ready for SI continuity-approve once commit hash is stamped below.
- Commit: pending (see git log `fix(gateway): include SOUL on lead Ollama soft-fail prompt`).
