# Jaeger Surfaces — product break log

**When:** 2026-09-11 ~08:47 PT  
**Branch:** `finish-alpha` @ `09c772c`  
**WebUI submodule:** `vendor/hermes-webui` @ `5bb06e75`  
**Scorecard:** `docs/product-acceptance.md`  
**Owner:** Jaeger Surfaces

## P0 (must be empty for P5)

_None._

## Open / accepted (non-P0)

| ID | Severity | Surface | Issue | Status |
|----|----------|---------|-------|--------|
| B1 | P2→mitigated | WebUI | User-facing Hermes title/placeholder | **Fixed** — `<title>Jaeger</title>`, titlebar, composer; MutationObserver + static HTML scrub |
| B2 | P3 | WebUI | Residual Hermes copy in Settings/Help/onboarding/SVG plumbing | **Mitigated** — user-visible Settings/onboarding/health scrubbed; keep `hermes-theme` localStorage keys / CSRF header names (vendor plumbing, not chrome) |
| B3 | P3 | Mac GUI | Chat GUI drive / TCC | **Parked** — Matthew stand-down; keep P4 yellow; no more TCC asks |
| B4 | P3 | WebUI | Avatar/Work stages are chrome stubs (composer stays) | Open — product parity next |
| B5 | P3 | Gateway↔Surfaces | Specialist *turn identity* binding | **Sample live** — Gateway `1e6b058` `turn.finish` has `agent_id`/`role`/`display_name`; Surfaces chrome next |

## Evidence (happy path)

- **P1 agents parity:** WebUI `/api/agents` IDs == Gateway `/v1/agents` (incl. `lead` + 6 `specialists`). Files: `webui-agents.json`, `gateway-agents.json`.
- **P2 chrome:** Live HTML `<title>Jaeger</title>`, `appTitlebarTitle=Jaeger`, `Message Jaeger…`. Desktop capture: `product-desktop.png`.
- **P3 WebUI turn:** prior SSE `pong` (M4).
- **P4 Mac GUI:** blocked — see `p4-gui-tcc-block.txt`, `m5-gui-ax-blocker.txt`. Spine: `bridge.sock` `pong`.
- **P6 specialist:** session handoff → `native:everyday` → assistant `everyday-pong`.
- **P8 approval:** WebUI card + proxy `POST /api/agents/*/handoff` + `/api/approvals/*`; Mac `ApprovalSheetView` exists.

## Commits (not pushed unless Matthew asks)

- `09c772c` / submodule `5bb06e75` Hermes residue scrub + break-log path  
- `5fd1c24` lead + specialists chrome wire  
- `e195873` Jaeger title + handoff approval card  
- `82c9bab` Chat/Avatar/Work stage pills  
- `4aecd61` unify AGENTS catalog  

## Auditor notes

- In-repo copy: `docs/product-break-log.md` (from `~/workspace/surfaces-overnight/product-break-log.md`).
- P2 Auditor list scrubbed in vendor i18n/ui (Welcome/not responding/Official Dashboard/plugins+help). CSRF/`hermes-*` keys untouched.
- P4 GUI remains yellow/blocked per Matthew stand-down.


- **P2 yellow:** primary chrome fixed; additional user-visible Hermes scrubbed. Remaining HTML `Hermes` hits (5): `X-Hermes-CSRF-Token`, `openHermesDashboard` handler name, `__HERMES_EXTENSION_CONFIG__` — vendor plumbing, not bookmark chrome.
- **P5 yellow:** break log was missing — **this file**. P0 list empty.

## S2 skip (2026-09-11 Surfaces)
- **Skipped:** Marketplace-style Plugins + Bots sheet — no clear in-place Mac Settings / WebUI hook beyond existing vendor Settings → Plugins / Extensions tabs; inventing a Grok-like marketplace is out of small-scope polish.
- **S3 landed:** WebUI roster clicks use `activateAgent` (commit on finish-alpha); Mac already activated via GatewayClient.activateAgent; approval card reserved for API `pending_approval`.
