# Jaeger unified UI — design system

Base tokens: `src/shell/tokens.jaeger.css` (surfaces, foreground opacity tiers, accent, avatar hues,
light/dark). Refinement layer: `src/unified/design.css`. Primitives: `src/unified/ui.tsx`.
No third-party fonts, icon packs or CSS frameworks: system font, the in-repo SF-Symbols-style
icon set (`components/Icons.tsx`, 24px grid, round caps/joins, one stroke weight per size).

## References used
- Apple Human Interface Guidelines — Layout, Typography, Materials, Color/Accessibility, Motion
  (developer.apple.com/design/human-interface-guidelines). Source of the macOS text-style scale,
  vibrancy materials for chrome (dock, tab bar, popovers, sheets), Control Center tile pattern,
  and "reduce motion" behaviour.
- Refactoring UI principles (Wathan & Schoger): limited spacing and type scales, hierarchy by
  weight and colour rather than size alone, fewer borders, empty states as design surfaces.
- Radix UI / shadcn/ui patterns (github.com/radix-ui, github.com/shadcn-ui/ui): segmented control as
  a `radiogroup` with roving tabindex and arrow keys, modal sheet with focus capture + Escape,
  toasts in a polite live region. Patterns only; no code copied.
- WCAG 2.2 AA: 4.5:1 body text (text tiers ≥ 54% foreground on our surfaces), visible focus.

## Rules
- **Spacing**: 8pt grid — `--jg-space-1..7` = 4, 8, 12, 16, 24, 32, 48. 4 is for icon/text gaps only.
- **Type**: caption 11 · footnote 12 · body 13 · callout 14 · headline 15/600 · title3 17 · title2 20 ·
  title1 24/700 (page titles) · large 28. Secondary text uses opacity tiers, not new greys.
- **Radii**: 8 controls · 12 popovers/toasts · 16 cards/inspectors · 22 tiles and sheets.
- **Materials**: `--jg-material` (72%) and `--jg-material-thick` (86%) of the elevated surface with
  `saturate(180%) blur(24px)` — dock, phone tabs, popovers, sheets, toasts, Control Center tiles.
- **Motion**: `--jg-ease-spring` over `--jg-dur-spring` (320ms) for press/appear; fades 200ms.
  `prefers-reduced-motion: reduce` collapses all durations to 1ms.
- **Focus**: `:focus-visible` gets `--jg-focus` (3px accent ring at 45%). Never remove outlines without it.
- **Status tones**: ok = green, warn = yellow, bad = red (avatar hues), always paired with a word.
- **States**: every data region has loading (`SkeletonRows`), empty (`Empty` with an action where one
  exists) and error (`.jg-u-error`, `role="alert"`). Transient results use `useToast()`.
- **Layout**: page = header (title + one-line purpose, then a `.jg-ui-toolbar` with primary action
  last) → content → optional `.jg-ui-inspector` in a `.jg-ui-split`. Forms open in a `Sheet`.
- **Data**: live data only. If a backend is missing, the control is disabled with a setup note; no
  fabricated values or placeholder content.
