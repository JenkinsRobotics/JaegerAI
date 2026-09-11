# Jaeger spine acceptance (auditor scorecard)

**End goal:** Jaeger passes as a daily-driver host — one gateway spine, real chat turns from Mac + WebUI, own + third-party agents visible, honest health. Not a rewrite. Not “Grok Bot complete” marketing.

**Done when:** all **Must** IDs are GREEN on **two** real probe sessions ≥30 minutes apart.

**Locked endpoints:**
- Ollama: `http://192.168.64.1:11434`
- WebUI: `http://100.74.2.15:8790/`
- Gateway: `http://127.0.0.1:8810`
- Do **not** treat `:8813` (ares-agentgateway) as the chat spine.

## Must (fail the build if any red)

| ID | Requirement | Proof |
|----|-------------|--------|
| M1 | Gateway `:8810` running and stays up after start | health curl; still up after 5 min |
| M2 | `GET /v1/agents` lists native + Hermes/OpenClaw/Roundtable | JSON includes all four |
| M3 | Activate agent works | `POST /v1/agents/{id}/activate` 2xx |
| M4 | Real text turn via WebUI returns model text | send ping; capture reply (not error toast) |
| M5 | Real text turn via Mac Chat (same spine) | send ping; capture reply |
| M6 | Profile catalog shows all 4 profiles with display names | API/UI evidence |
| M7 | Profile switch works (no 400) | switch each profile once |
| M8 | Health fail-closed when brain/bridge dead | kill bridge → not “all green” |
| M9 | Chat does not require `:8813` ARES gateway | turn works with `:8813` down |
| M10 | Locked IPs only in config/defaults for these roles | grep/config review |

## Should (same pass if Must already green)

| ID | Requirement |
|----|-------------|
| S1 | Todos tab not 404 (fix API or hide tab) |
| S2 | Mac sidebar AGENTS == `/v1/agents` |
| S3 | `verify-stack-smoke.py` 0 required failures |
| S4 | Finance session default under `~/.jaeger/finance` |
| S5 | ARES/system transducers gated default-off |

## Stretch (do not block done)

| ID | Requirement |
|----|-------------|
| X1 | Playwright e2e in CI |
| X2 | Hermes-class cron/learning |
| X3 | OpenClaw-class channel mesh |
| X4 | SI character-sheet / memory parity |

## Auditor loop

1. Probe Must → RED/YELLOW/GREEN per ID with evidence  
2. File breaks with exact error + repro  
3. Gateway / Surfaces fix  
4. Re-probe failed IDs only  
5. Repeat until Must all GREEN × 2  

**Auditor job:** keep saying NO until M1–M10 have evidence — not until the tree “looks bigger.”
