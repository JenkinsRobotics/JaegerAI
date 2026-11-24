# SPEC-03: Web UI

## Context
On 2026-10-19 (12235c56) the inherited Hermes static frontend (`features/webui/static/style.css`, with 21 `data-skin`s) was archived. The web UI is now the **canonical React UI** (`jaeger_ai/interfaces/ui`), served by `features/webui` (`api/ui_shell.py`, `api/routes.py`). The "skin switch" therefore becomes the canonical UI's `data-feel`.

## Scope
Map the skin/feel switch to the 7 v1 feels, make sure the 5 lookalike skins can never ship, set the favicon set to shield-blue, and set body text to 14px on the web.

## Files
- `jaeger_ai/interfaces/ui/index.html`: `<html data-surface="web">`. Add `<link rel="icon" href="/jaeger-icon.svg">`, PNG 32/192 and `apple-touch-icon` (180), with `?v=<hash>` cache-busting.
- `jaeger_ai/interfaces/ui/public/jaeger-icon.svg`, `jaeger-icon-180.png`, `jaeger-icon-512.png`: replace with `assets/shield-blue.svg`, `-180.png` and `-512.png`. Add `-32.png` and `-192.png`.
- `jaeger_ai/interfaces/ui/public/manifest.webmanifest`: update the icons (192/512, `purpose: any`) and set `theme_color` to `#0b62d6`.
- `/favicon.ico` (`features/webui/api/routes.py:11876-11878`, served from `static_root`): ship `assets/favicon.ico` (16/32/48/64 from shield-blue) at that root.
- Feel switch: the same `AppearancePanel` as SPEC-01, which sets `html[data-feel]`. Values are exactly `jaeger | shield-mono | ares-bronze | mission-control | aurora | vscode | grok`. Unknown or legacy values (old skin names such as `ares`, `aether`, `graphite`, `mono`) map as `ares`→`ares-bronze`, `mono`→`shield-mono`, and everything else → `jaeger`.
- **Remove the 5 lookalike skins:** `github`, `codex`, `terracotta`, `sienna`, `geist-contrast`. They're already out of the served bundle with the archive. If any archived `style.css` copy is still reachable by a route or packaging, delete those skin blocks from it. Add a CI grep against the built `dist/` so these names, and their signature hexes (`#0969DA`, `#D97757`, `#0070f3`), never appear.
- Body size: `jaeger.css` `[data-surface="web"]` sets `--jg-font-size-body: 14px` (line height 22px). The native host sets `data-surface="native"`, which stays at 13.

## Acceptance criteria
- [ ] The browser tab shows the shield-blue favicon at 16 and 32. PWA install shows the 512 icon. After an icon change, a hard reload isn't needed (`?v=` hash).
- [ ] All 7 feels × light/dark are selectable on the web and persist in localStorage. Legacy skin values migrate as described.
- [ ] No lookalike skin name or signature hex is in the built web bundle (CI grep).
- [ ] Computed body text is 14px on the web and 13px in the Mac app (same build, different `data-surface`).
- [ ] **WCAG AA:** an axe-core run with no contrast violations on chat, settings and sidebar for each feel × mode. The token gate passes.

## Out of scope
Reviving the archived Hermes frontend, the `chatgpt`/`claude`/`gemini` feels, and server-side theming.
