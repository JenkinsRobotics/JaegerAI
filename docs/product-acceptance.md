# Jaeger product acceptance (post-spine)

Spine Must (docs/spine-acceptance.md) is prerequisite. This scorecard is the **product** bar Matthew ordered 2026-09-11.

**End goal:** Unified Mac + WebUI experience; no known UI P0 bugs on the happy path; lead + standing specialists with pull-in — Grok-shaped, then surpass. All code lives in the JaegerAI repo only.

**Done when:** Product Must P1–P8 green on two probes ≥30m apart.

## Product Must

| ID | Requirement | Proof |
|----|-------------|--------|
| P1 | Mac and WebUI show the **same** agent catalog from Gateway `:8810` | Side-by-side list IDs match |
| P2 | Shared chrome: Chat-centric nav + agent switcher + Jaeger branding (not Hermes-first) on both faces | Screenshots / UI dump |
| P3 | WebUI happy path: new chat, send turn, switch agent/profile — no error toast | Real turn |
| P4 | Mac happy path: Chat window visible, send turn, switch agent — no crash | Real turn (GUI if TCC granted; else document blocker + API) |
| P5 | No P0 UI bugs on checklist (profile switch, agents list, composer, sessions) | Break log empty for P0 |
| P6 | Lead assistant can hand off / call at least one specialist agent | Live or tested handoff |
| P7 | Standing specialists registered in-repo (AgentRegistry) — not fake sidebar names | Registry + UI list |
| P8 | Pull-in / approval path works for a gated tool (human decision) | Approval card once/deny |

## Should
| ID | Requirement |
|----|-------------|
| S1 | Mac GUI automation (Accessibility + Screen Recording granted) |
| S2 | Marketplace-style Plugins + Bots sheet (Grok-like) |
| S3 | Zero approval-loop stalls on simple pings |

## Stretch
| ID | Requirement |
|----|-------------|
| X1 | Clearly surpasses Grok Bot (multi-specialist autonomy + channels) |
| X2 | Playwright e2e in CI |

## Rules
- All implementation in `/Users/matthewjenkins/GitHub/JaegerAI` only.
- Fix-in-place; gateway spine stays `:8810`.
- Auditor keeps saying NO until Product Must green ×2.
