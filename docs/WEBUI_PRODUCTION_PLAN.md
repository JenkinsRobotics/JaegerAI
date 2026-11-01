# JaegerAI Web UI — Production Readiness Audit & Plan

**Date:** 2026-11-01
**Reference app:** `hermes-webui/` (v0.51.792, in this GitHub folder) — the benchmark for "full-fledged agent web UI"
**Scope:** `jaeger_ai/interfaces/ui/` (React 19 + TS + Vite 7 SPA, symlinked as `apps/web`), served by `jaeger_ai/features/webui/` on :8790, proxying the aiohttp Gateway (`jaeger_ai/core/gateway/server.py`)

---

## 1. What JaegerAI already has (the good — keep it)

The backend spine is **more advanced than Hermes**:

- Gateway-owned `/v1/*` API (sessions, agents, approvals, tasks, orchestration, widgets, runtime) + SSE event spine (`/v1/sessions/{id}/stream`, `/v1/events/stream`) with cursor resume, plus WebSocket `/ws` and OpenAI-compat endpoints.
- WebUI proxy layer on :8790 with cookie/passkey auth + CSRF meta token, server-side caller credential — the browser never holds a gateway token.
- A real design system: `DESIGN.md` + `ui/DESIGN.md`, `--jg-*` tokens (`shell/tokens.jaeger.css`), primitives (`unified/ui.tsx`: Sheet, Toast, Segmented, SkeletonRows, Empty, error states), Apple-native aesthetic, responsive container-query tiers (compact→wide), phone shell with bottom tab bar.
- 174 Vitest files, build guards (`check-theme-literals.mjs`, `check-no-mock.mjs`), Playwright config with 5 projects.
- Rich feature surface: chat w/ queue/approvals/clarify/handoffs/attachments, agents roster + memory/knowledge, characters, tasks, automations, skills, library, research/YouTube, studio, models/compare, machine control, widgets grid, avatar, 12 settings panels, first-run gate, ⌘K palette.

## 2. Audit findings — broken / draft / inconsistent (the debt)

| # | Finding | Evidence |
|---|---------|----------|
| 1 | **Two competing shells**: `AppShell.tsx` (legacy, "Modified from AetherStudio") vs `AppChrome.tsx` ("replaces the old bottom dock", 2026-10-31). `AppShell` still has tests. | `src/shell/AppShell.tsx`, `AppChrome.tsx`, `AppShell.test.tsx` |
| 2 | **29 CSS files**, layering debt: feature pages import each other's CSS (`SharePointPanel.tsx:17` imports `windows/bots-page.css`; `CheckpointsView.tsx:7` imports `unified/workspaceBrowser.css`; `DangerReset.tsx:3` imports widgets `host.css`). | `src/**/*.css` (29 files) |
| 3 | **Stale e2e spec**: `tests/e2e/apple-ui.spec.ts` targets the retired `?ui=apple` UI (old selectors, redirects now) — the only Playwright spec, so e2e coverage of the real UI is effectively zero. | `tests/e2e/apple-ui.spec.ts` |
| 4 | **Legacy scaffolding pervasive**: `?ui=` switch + `LEGACY_PATHS` (`router.ts:27,84-99`), `LEGACY_SETTINGS` (`settings/registry.ts:17`), `LEGACY_IDS` (`WindowManager.tsx:47`), stale draft keys `jaeger.ui.*.draft.v1.*`. | router.ts, registry.ts, WindowManager.tsx |
| 5 | **Doc/code drift**: `DESIGN.md:61` says compact tab bar = Home/Chat/Work/Machine/More; code shows Home/Chat/Agents/Work + More. `ui_shell.py` `UI_PAGES` frozenset hand-duplicates the router. Docs cite removed files (`AppleApp.tsx`, `PinnedAgents.tsx`). | DESIGN.md, `AppChrome.tsx`, `api/ui_shell.py:133`, docs/ARCHITECTURE_CONTROLLER_PATTERN.md:277 |
| 6 | **Stubs & deprecated leftovers**: avatar lip-sync STUB (`avatar/useAvatar.ts:20`); native bridge `notImplemented` (`platform/native.ts:36`); `legacy` sub-tab in MachineControlPanel (`:29,170`); FinancePanel deprecated w/ hidden tests; retired-widget placeholder UI. | see files |
| 7 | **Inconsistent formatting**: minified one-liner style in `agents/*`, `chat/*` vs normally formatted `shell/`, `unified/`, `windows/`; inline `import('./source').X` types in `api/gateway.ts`. | codebase-wide |
| 8 | **Symlink duplication confusion**: `apps/web/` mirrors `interfaces/ui/` incl. committed `test-results/`. | `apps/README.md`, `apps/web/test-results/` |
| 9 | **Possible missing script**: `apps/macos/Scripts/build-main-screen.sh` → `interfaces/ui/scripts/build-external.py` (not present in `ui/scripts/`). | apps/macos/Scripts/ |
| 10 | **Frontend lacks Hermes-parity surfaces**: no workspace file browser w/ preview+git in the unified UI (exists only as `WorkspaceBrowser` page?), no embedded terminal, no cron/skills/memory *panels as first-class sidebar views*, no Control Center consolidation, no skins/themes beyond light/dark, no i18n, no PWA/offline, no voice in web UI, no onboarding wizard parity. | compare `hermes-webui/static/panels.js`, `workspace.js`, `boot.js` |

## 3. Gap analysis vs Hermes WebUI (what "full-fledged" means)

| Capability | Hermes | JaegerAI today | Gap |
|---|---|---|---|
| Chat streaming | SSE + run-journal replay, Last-Event-ID resume, steer/queue/interrupt | SSE w/ cursor resume, queue, approvals, clarify | Mostly parity; add steer/interrupt parity, run-journal replay |
| Sessions | list/groups/search/pins/archive/import/export/branch, cross-tab SSE sync | history panel + search | add projects/tags, import/export, cross-tab sync |
| Workspace browser | tree + preview (md/mermaid/katex/code/pdf/img) + edit + git badge/ops + upload + terminal | WorkspaceBrowser page; no terminal, thin git | big gap |
| Control surfaces | sidebar panels: Cron, Kanban, Skills, Memory, Todos, Profiles, Settings modal | scattered pages (Work/Research tabs) | consolidate into one nav model |
| Composer footer | model/profile/workspace chips always visible + context ring | composer exists; verify chips | parity check |
| Theming | 3 modes × 21 skins, CSS vars, font-size scale | light/dark via tokens | add skins + font scale |
| i18n | 15 locales | none | gap |
| Mobile/PWA | bottom nav, dvh, safe areas, SW offline shell | phone shell, PWA manifest per DESIGN.md | verify SW offline |
| Voice | dictation + TTS in web | voice nodes exist (kokoro/whisper); wire to web | gap |
| Security | CSP headers, signed cookies, passkeys, CSRF, safe_resolve, SSRF guards | auth+CSRF on webui proxy | port header/CSP hardening to :8790 server |
| Tests | ~11.5k pytest + browser smoke + Docker smoke CI | 174 vitest + 1 stale playwright spec | add real e2e + server tests |
| Ops | bootstrap/start/ctl.sh/Docker/nix | run-jaeger-webui.sh + service.py | parity |

## 4. Plan — phased roadmap

### Phase 0 — Stop the bleeding (1 sprint): make the draft build & pass clean
1. Delete or quarantine `AppShell.tsx` + its test; make `AppChrome` the only shell. 
2. Replace the stale `apple-ui.spec.ts` with real e2e specs against the built UI (chat send/receive via mocked SSE, navigation across the 9 pages, approvals flow) across the 5 existing Playwright projects, run against :8790 with `JAEGER_WEBUI_UI_DIST` set.
3. Fix doc drift: DESIGN.md tab list, sync `ui_shell.py` `UI_PAGES` from a single generated source (export route table from `router.ts` at build time), remove dead doc references (`AppleApp.tsx`, `PinnedAgents.tsx`), verify/fix `build-external.py` reference.
4. Fix `apps/web` symlink hygiene (exclude node_modules/dist/test-results from anything committed).
5. Add missing states audit: every data region gets Skeleton/Empty/Error per `ui/DESIGN.md`; run axe + the 5 audit viewports (390/412/673/1024/1440) light+dark via the `ux-audit` skill workflow.

### Phase 1 — One design language (1–2 sprints): kill the inconsistency
1. Consolidate CSS: one tokens file (`tokens.jaeger.css`) + one primitives stylesheet (`unified/design.css`) + per-page CSS only where genuinely page-scoped; remove cross-page CSS imports; enforce via `check-theme-literals.mjs` extension (no hard hex/px outside token files, no cross-feature css imports — add a lint rule).
2. Pick one chrome (`AppChrome`), remove `?ui=` switch + `LEGACY_PATHS`/`LEGACY_SETTINGS`/`LEGACY_IDS` after a deprecation release; keep redirects server-side only.
3. Remove dead code: `legacy` machine sub-tab, FinancePanel, retired-widget placeholder, avatar STUB (implement viseme-driven lip-sync or remove the claim), dev-only mocks already guarded — keep guards in build.
4. Normalize code style: run Prettier/ESLint (`eslint.runtime-guard` exists in hermes — port the pattern) across `src/`; ban inline dynamic type imports in `api/gateway.ts` in favor of `import type`.
5. Gate: `npm run build` + `npm test` + new Playwright suite green in CI before merging anything else.

### Phase 2 — Hermes-parity product surface (2–3 sprints): the "full-fledged agent" feel
1. **Workspace panel**: port Hermes `workspace.js` behaviors onto the Gateway contract — file tree, preview (md/mermaid/KaTeX/code/images/pdf), inline edit/save, create/rename/move/mkdir, chunked upload (already exists at `/v1/sessions/{id}/uploads` — reuse), git badge + stage/commit/pull/push against a registered workspace, embedded terminal view (new `/v1/terminal/*` gateway routes, jailed to workspace root).
2. **Control Center consolidation**: single settings/control modal (port Hermes Control Center model: preferences, import/export conversations, clear, providers) launched from sidebar footer; move Automations/Skills/Memory/Tasks into first-class sidebar sections of the Work tab with consistent PageHeader+toolbar anatomy.
3. **Sessions UX**: projects/tags chips, pins, archive, search, import/export JSON, cross-tab sync via BroadcastChannel + `/v1/events/stream` subscription; branch/fork.
4. **Composer footer chips**: model / agent / workspace pickers always visible + context ring (token usage), matching Hermes composer; voice buttons (dictation → `/v1/transcribe`, TTS → `/v1/tts`) wired to existing kokoro/whisper modules.
5. **Approvals everywhere**: approval cards in chat + a global tray (exists) + Approvals count in menu-bar-equivalent chrome (web: topbar badge), deep-linkable.
6. **Slash commands**: command palette exists (⌘K); add `/`-commands in composer with autocomplete (port `commands.js` registry pattern over gateway verbs).

### Phase 3 — Production hardening (ongoing, parallel)
1. **Theming**: add skin system (`data-skin` attribute like Hermes' 21 skins) on top of `--jg-*` tokens; font-size scale; persist; axe-verify contrast per skin.
2. **i18n**: extraction pass + `t()` wrapper, start with en; structure ready for more locales.
3. **Security parity**: port Hermes `helpers.py` security headers + CSP (with report endpoint) to `features/webui/server.py`; audit `safe_resolve`-style path containment on every `/v1/documents|/v1/studio` file route; SSRF guards on research/YouTube fetchers; rate-limit login.
4. **Ops**: `ctl`-style daemon wrapper for the :8790 service (hermes `ctl.sh` as template), Dockerfile + compose for JaegerAI webui+gateway, service worker for offline shell (deploy a real `sw.js`; today only a kill-switch exists in `ui_shell.py`).
5. **Tests**: browser smoke in CI (port Hermes `tests/browser_smoke.py`), Docker smoke, pytest for new `/v1/terminal` + workspace routes; keep the no-mock & theme-literal guards; add a CI job running the 5-viewport screenshot matrix (scripts/screenshots.mjs exists — wire it).
6. **Docs**: one `docs/WEBUI.md` (architecture + how to extend), update README feature table to match reality (mark experimental vs built per `docs/architecture/ARCHITECTURE.md` convention).

### Phase 4 — Polish & ship gate (before "production" claim)
1. Full `ux-audit` pass (Nielsen heuristics + axe WCAG 2.2 AA + 390/412/1024/1440 light/dark) on every tab; zero critical a11y issues.
2. Performance: route-level code splitting already present — verify bundle size budget in CI; lighthouse PWA score ≥ 90.
3. Release checklist: changelog, version bump, `Install Jaeger AI.command` smoke, webui served from :8790 smoke, remote Tailscale access doc.

## 5. Definition of done (production app, not demo)
- [ ] One shell, one router, one tokens file; no legacy switches; build guards + lint green.
- [ ] Real Playwright e2e suite (≥ chat, sessions, workspace, approvals, settings) green on 5 projects in CI.
- [ ] Workspace file browser + terminal + git ops working against the gateway.
- [ ] Control Center modal + sidebar sections consistent; every region has loading/empty/error.
- [ ] Skins + font scale + i18n scaffolding; axe AA clean at all audit viewports, light & dark.
- [ ] Security headers/CSP on :8790; path containment + SSRF guards tested.
- [ ] Ops: ctl-style daemon, Docker, offline SW, Tailscale remote doc.
- [ ] README/docs match shipped behavior.

## 6. Suggested first work items (concrete, small, high-signal)
1. Delete `AppShell.tsx` + merge its unique behaviors into `AppChrome`; delete stale `apple-ui.spec.ts`, add `chat.spec.ts` + `nav.spec.ts` e2e.
2. Add ESLint+Prettier config and format pass (single PR, mechanical).
3. Generate `UI_PAGES` for `ui_shell.py` from `router.ts` exports; fix DESIGN.md drift.
4. CSS consolidation lint rule (no cross-feature `.css` imports) + fix the 3 offenders.
5. Implement context ring + model/agent/workspace chips verification in composer against `/v1/runtime/*`.
