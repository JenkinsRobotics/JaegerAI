# SPEC-00: Shared tokens package

**Status:** approved 2026-10-21. **Base commits:** JaegerAI `master` 2bfd47c5 (2026-10-21), AetherStudio ece0209, jaeger-chat `jaeger-tab` 0910505.

## Scope
Create one token package and replace every drifted copy with its generated output.

## Package
- **Name:** `@jaeger/design-tokens` (npm) / `jaeger-design-tokens` (SwiftPM, Python).
- **Location:** `JaegerAI/packages/jaeger-design-tokens/` (the monorepo already has `packages/`).
- **Layout:** `tokens/jaeger-tokens.json`, `build/build-tokens.(mjs|py)`, `dist/*`, `assets/` (icons and avatar), `CHANGELOG.md`.
- **Versioning:** semver, starting at 1.0.0. Consumers in other repos vendor `dist/` at a pinned tag and record its sha256 in `VENDORED.json`.

## Build
Follow `tokens/BUILD-SPEC.md`. Use `npm run build` (or `python3 build/build_tokens.py tokens/jaeger-tokens.json dist`). The CI job runs the build, the contrast gate, the literal check and the vendored-hash check.

## Copies to replace (exact paths)
| # | Copy | Replace with |
|---|---|---|
| 1 | `JaegerAI/jaeger_ai/assets/design-system/tokens.css` + `aether-default.json` | delete. Add a README pointing to the package |
| 2 | `JaegerAI/jaeger_ai/interfaces/ui/vendor/aether-ui/tokens/tokens.css` (+ `tokens.json`, `home.css` token block) and `vendor/assets/themes/aether-default.json` | vendored `dist/jaeger.css` + `dist/aether.css` |
| 3 | `AetherStudio/core/ui/tokens/tokens.css` (+ `tokens.json`, `home.css` token block) | vendored `dist/jaeger.css` + `dist/aether.css`, `data-brand="aether"` |
| 4 | `AetherStudio/core/assets/themes/aether-default.json` | generated from the package (brand=aether) |
| + | `JaegerAI/jaeger_ai/interfaces/ui/src/shell/tokens.jaeger.css` (hand-written `--jg-*`) | `dist/jaeger.css` (import in `ui/src/main.tsx:5`) |
| + | `JaegerAI/jaeger_ai/interfaces/tui/theme.py` `_ACCENT_HEX` | `dist/theme.py` |

## Migration map (old → new)
| Old | New |
|---|---|
| `--aether-color-bg-app` / `-shell` / `-bar` | `--jg-bg` |
| `--aether-color-bg-panel` / `-rail` / `-inset` / `-control` | `--jg-surface` / `--jg-sidebar` / `--jg-inset` / `--jg-raised` |
| `--aether-color-bg-hover`, `-row-hover` | `--jg-inset` |
| `--aether-color-border` / `-control` / `-focus` | `--jg-border` / `--jg-border-strong` / `--jg-focus` |
| `--aether-color-text` / `-soft` / `-dim` / `-faint` | `--jg-text` / `--jg-text-2` / `--jg-text-2` / `--jg-text-3` |
| `--aether-color-accent` / `-strong` / `-icon` | `--jg-accent` / `--jg-accent-hover` / `--jg-accent-text` |
| `--aether-color-ok/warn/error` | `--jg-ok/warn/error` (light values now adapted) |
| `--aether-space-1…5` (3/5/7/9/13) | `--jg-space-1, 2, 2, 3, 4` (4/8/8/12/16) |
| `--aether-radius-control/button/field/row` (7/8/6/6) | `--jg-radius-sm/md/sm/sm` (6/8/6/6) |
| tokens.jaeger.css `--jg-color-chrome` / `-pane` / `-sidebar` / `-elevated` | `--jg-bg` / `--jg-surface` / `--jg-sidebar` / `--jg-raised` |
| `--jg-font-size-base: 14px` | `--jg-font-size-body` (13; 14 under `[data-surface="web"]`) |
| accents #4c9dff, #2f7fe0, #1680f3, #3aa0ff, #3269ff, #58a6ff, #1e88e5 | `--jg-accent` / `--jg-accent-text` |

## Acceptance criteria
- [ ] The package builds and `contrast-report.json` shows **0 fails** (648 checks at v1.0.0), WCAG 2.x AA.
- [ ] None of the 4 copies remains as hand-written tokens. `rg -- "--aether-space-1: 3px"` returns nothing across JaegerAI and AetherStudio.
- [ ] The vendored sha256 matches the pinned tag, and CI fails on a 1-byte edit.
- [ ] `dist/aether.css` lets un-migrated `--aether-*` call sites render unchanged, apart from intended value changes.
- [ ] Visual diff screenshots of the canonical UI (light/dark) are attached to the PR.

## Out of scope
The `chatgpt`, `claude` and `gemini` feels (later), new components, and the icon pipeline beyond copying `assets/`.
