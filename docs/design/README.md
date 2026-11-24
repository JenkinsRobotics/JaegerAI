# Jaeger design system: implementation specs v1.0.0 (approved 2026-10-21)

Read-only deliverable. No repo has been edited. Start with SPEC-00, because the other four depend on its package.

| File | For |
|---|---|
| `tokens/jaeger-tokens.json` | single source of truth (W3C tokens): light/dark, brand, neutrals, text, status, 8 tints, type 13/14, 4px space, radius, motion, sound ids, 7 feels, aether brand |
| `tokens/contrast-report.json` | 648 WCAG AA checks, **0 fails** |
| `tokens/BUILD-SPEC.md` + `build/build_tokens.py` | build spec + reference build. Sample outputs are in `build/out/`; the Swift passes `swiftc -typecheck` |
| `SPEC-00-shared-tokens.md` | package, the 4 drifted copies, migration map |
| `SPEC-01-mac-app.md` | Jaeger Mac App bot |
| `SPEC-02-ide-chat.md` | Jaeger IDE Chat bot |
| `SPEC-03-webui.md` | web UI (canonical UI after the 2026-10-19 archive) |
| `SPEC-04-aether.md` | AetherStudio + Aether-* |
| `assets/` | shield-blue (default, 16–1024, favicon.ico), shield-dark/light, the monochrome shield-template (22/44), avatar-bronze full/face crops |

**Defaults:**
- feel `jaeger`
- stream `jaeger`
- icon `shield-blue`
- avatar `bronze-helmet`
- body 13 (app/IDE) / 14 (web)

Feels deferred to later: `chatgpt`, `claude`, `gemini`.
