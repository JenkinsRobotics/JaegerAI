# SPEC-04: AetherStudio and the Aether-* repos

## Scope
Apply the shared tokens with `data-brand="aether"` (Aether Indigo accent on the Jaeger neutrals), and move all spacing onto the 4px grid.

## Files
**AetherStudio (ece0209):**
- `core/ui/tokens/tokens.css`, `tokens.json`, and the token block in `home.css`: replace with the vendored `jaeger.css` + `aether.css` (SPEC-00 #3).
- `core/assets/themes/aether-default.json`: regenerate from the package (#4). Joint `#8b87ff` → `#c38bff`. Part `#36d6c3` and hardware `#ff8a3d` are kept.
- 4px-grid fix, replacing `--aether-space-*` and literal 3/5/7/9/13px paddings and gaps (counts from `rg`):
  - `core/ui/src/widgets.css` (132)
  - `onshape mockup/app/globals.css` (92; mockup, so lower priority)
  - `Aether CAD/src/react/shapr-shell.css` (75)
  - `Aether CAD/src/style.css` (48)
  - `studio/src/setup.css` (21)
  - `studio/src/studio.css` (18)
  - `studio/src/library.css` (15)
  - `aether-animation/web/src/app.css` (7)
  - `Aether CAD/src/feature-authoring.css` (6)
  - `Aether CAD/src/sketch-workspace.css` (5)

  The rule: 3→4, 5→4, 7→8, 9→8, 13→12 (or 16 where it's a section gap). Borders and 1px hairlines are exempt, and 2px is allowed for nudges only.
- Root element: `data-brand="aether"`, with `data-mode` following the system appearance.

**Aether-Animation, Aether-CAD, Aether-IO, Aether-Map, Aether-Sketch, Aether-Vector:** each has only `docs/index.html` styled (31 hits each of the shared docs palette `#0a0e14` / `#58a6ff` / `--accent`). Replace the inline `:root` vars with a `<link>` to the vendored `jaeger.css`, add `data-brand="aether"`, and map `--bg/--panel/--fg/--muted/--accent/--border` to `--jg-bg/--jg-surface/--jg-text/--jg-text-2/--jg-accent-text/--jg-border`. Radius 10 → `--jg-radius-lg` (12).

## Acceptance criteria
- [ ] `rg -e "--aether-space-[1-5]:\s*(3|5|7|9|13)px"` returns 0. A lint script flags new off-grid padding, margin and gap values (`[0-9]*[13579]px` except 1px).
- [ ] AetherStudio light and dark both use Aether Indigo:
  - light: fill `#5048d8`, white text 6.44
  - dark: fill `#6158e8`, white text 5.16; accent text `#9c96ff` at 7.08 on surface
  - All status and text pairs pass AA as in `contrast-report.json` (`aether/light`, `aether/dark`).
- [ ] The CAD viewport colors are unchanged apart from the joint hue. A screenshot diff is attached.
- [ ] All 6 Aether-* docs pages render in light and dark with no contrast violations (axe).

## Out of scope
The archived Swift apps (`aether-animation/archive/**`, `dev/archive/**`), CAD geometry rendering, and new Aether components.
