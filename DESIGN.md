# DESIGN.md: Jaeger

The format follows [awesome-design-md](https://github.com/VoltAgent/awesome-design-md). Written 2026-10-31 from the live unified UI code (`jaeger_ai/interfaces/ui/src/shell/tokens.jaeger.css`, `src/unified/design.css`, `src/unified/ui.tsx`) and the approved Design & Style specs (`~/Documents/Jaeger-Design-Specs/`: `family/RESPONSIVE-SYSTEM.md`, `SPEC-00-shared-tokens.md`, `tabs/*`, `tabs/widgets/WIDGETS-SPEC.md`). Where this file and an approved tab spec disagree, the tab spec wins. Agents must read this file before any UI work.

## 1. Visual theme and atmosphere
A quiet, native-feeling Apple workspace for running agents: calm neutral surfaces, one blue accent, translucent "materials" for chrome, and dense but readable information. It should feel like a macOS app (Finder/Xcode/Settings) and the Grok/ChatGPT desktop apps, not a marketing site. Live data only: no fake numbers or placeholder content. When a backend is missing, show a disabled control with a setup note.
Stack: React 19 + TypeScript + Vite 7 with plain CSS custom properties (`--jg-*`). **No Tailwind, no CSS framework, no third-party fonts or icon packs.** Radix/shadcn are used as *patterns* only; no code is copied.

## 2. Color palette and roles
Neutrals come from one foreground color mixed at fixed opacity tiers. Never add new greys.
| Role | Token | Light | Dark |
|---|---|---|---|
| Window / chrome | `--jg-color-chrome` | #fcfcfc | #121212 |
| Pane | `--jg-color-pane` | #fcfcfc | #161616 |
| Sidebar | `--jg-color-sidebar` | #f5f5f5 | #0e0e0e |
| Elevated (cards, menus) | `--jg-color-elevated` | #ffffff | #1f1f1f |
| Foreground | `--jg-color-fg` | #1c1c1c | #f5f5f5 |
| Text secondary / tertiary / quaternary | `--jg-color-text-*` | fg at 68 / 56 / 40% | fg at 66 / 54 / 38% |
| Border / tertiary border | `--jg-color-border*` | fg at 12 / 8% | fg at 10 / 6% |
| Hover / active | `--jg-color-hover/active` | fg at 6 / 8% | same |
| Accent (Jaeger Blue) | `--jg-color-accent` | #1680f3 | #1680f3 (text #4d9bff) |
| On accent | `--jg-color-on-accent` | #fff | #fff |
| ok / warn / bad | `--jg-ok` / `--jg-warn` / `--jg-bad` | green #14c16f / yellow #f59312 / red #fb2b3e | same |
| Danger action | `--jg-danger` | #e5484d | #ff5a5f |
| Agent status | `--jg-status-working/approval/error` | accent / yellow / red | same |
| Avatar hues | `--jg-avatar-{blue,green,teal,purple,pink,orange,brown,red}` | per token | same |
Rules: status is **always color plus a word**. Body text tiers stay ≥54% foreground, which meets WCAG 4.5:1. There is one accent: don't introduce a second brand color.

## 3. Typography
System stack: `-apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif`. Base 14px/22px at weight 420; medium weight is 560.
Scale (`--jg-text-*`): caption 11 · footnote 12 · body 13 (shell/IDE) or 14 (web, approved) · callout 14 · headline 15/600 · title3 17 · title2 20 · title1 24/700 (page titles; 22 on compact/medium) · large 28 (empty states only).
Hierarchy comes from weight and opacity tier, not size alone. Lines are at most 72ch. iOS text inputs are ≥16px (no focus zoom). Respect Safari text zoom and Dynamic Type (`font: -apple-system-body` root, 13–20px clamp).

## 4. Components (`src/unified/ui.tsx`)
- **PageHeader**: title + one-line purpose, then `.jg-ui-toolbar` with the primary action last. Each tab has one header (no duplicate sub-tab titles).
- **Segmented control**: `radiogroup`, roving tabindex, arrow keys.
- **Sheet**: modal with focus capture and Escape; forms always open in a sheet. Bottom sheet with detents on compact.
- **Inspector** in `.jg-ui-split`: docked 320px (280–420), overlay or bottom sheet when narrower.
- **Toast** via `useToast()`, in a polite live region; undo for destructive actions.
- **States**: every data region has `SkeletonRows` (loading), `Empty` (with an action where one exists) and `.jg-u-error` with `role="alert"`.
- **Pills/status**: tone + label. **Cards**: radius 16, padding 12/16, 1px border, `--jg-shadow-card`.
- **Widget card**: `{kind, variant: data|control, size S/M/L/XL, params}` + a `load()` snapshot. Every control confirms first. The **e-stop** is the one exemption: one tap, always ≥44pt, never hidden.
- **Approvals**: every risky action goes through Work › Approvals (risky ones also need Touch ID). Widgets never approve something the inbox wouldn't.

## 5. Layout and spacing
4px grid tokens `--jg-space-1..7` = 4, 8, 12, 16, 24, 32, 48 (4 is only for icon/text gaps). Radii: 8 controls · 12 popovers/toasts · 16 cards/inspectors · 22 tiles and sheets.
Page anatomy: header, then toolbar, then content, then an optional inspector. Content is max 1120px on wide screens.

## 6. Depth, materials and motion
Materials for chrome (dock, tab bar, popovers, sheets, toasts, Control Center tiles): `--jg-material` (elevated at 72%) or `--jg-material-thick` (86%) + `backdrop-filter: saturate(180%) blur(24px)`. Shadows stay subtle: `--jg-shadow-card` and `--jg-shadow-control` (none in dark). Scrim is 50% light / 55% dark.
Motion: press/appear uses `--jg-ease-spring` (cubic-bezier(.34,1.36,.64,1)) over 320ms. Fades take 200ms, base 150ms and fast 100ms. Layout collapse uses 200ms `--jg-ease-out-quint`. `prefers-reduced-motion: reduce` sets every duration to 1ms. Don't add motion libraries without a reason; CSS first.
Focus: `:focus-visible` gets `--jg-focus` (a 3px accent ring at 45%). Never remove an outline without a replacement.

## 7. Icons
The in-repo SF-Symbols-style set (`components/Icons.tsx`, `src/icons.tsx`): 24px grid, round caps and joins, one stroke weight per size, `currentColor`. Native code uses real **SF Symbols** with matching names. Don't add icon packs (Lucide etc.) or ship Apple's SF Symbols as web assets (license).

## 8. Responsive rules (from RESPONSIVE-SYSTEM.md)
Use container queries on `.jg-app`, never device or user-agent sniffing. Everything must work from 320 to 2560px with no horizontal scroll.
| Class | Width | Device examples | Shell |
|---|---|---|---|
| compact | <600 | iPhone 390, Fold folded ~412, iPad Split 1/3 | bottom tab bar (Home, Chat, Work, Machine, More), push nav, sheets |
| medium | 600–839 | Fold unfolded portrait, iPad mini, Split 1/2 | 56px icon rail, inspector as a bottom sheet |
| regular | 840–1199 | iPad portrait 1024, small Mac windows | rail + 224px nav + content, overlay inspector |
| expanded | 1200–1599 | iPad landscape, Mac 1440 | 72px labeled rail + 248 nav + content + 320 inspector |
| wide | ≥1600 | big Macs | as expanded, content max 1120 centered |
- `short` (height <500): tab bar becomes a left rail; header is 44px.
- Foldable two-segment: list in segment 1, detail in segment 2, nothing across the hinge (`viewport-segment` env vars).
- Touch: targets ≥44×44 on `pointer: coarse` and ≥28 on fine, with ≥8px between targets. Every hover affordance has a touch equivalent.
- Safe areas: `viewport-fit=cover`, `env(safe-area-inset-*)`, `100dvh` (never `100vh`). The composer rides above the keyboard via `visualViewport` (`--jg-kb-inset`).
- Collapse order: inspector, then avatar, then section nav, then app nav. Tables become stacked rows on compact.
- PWA: standalone manifest, theme-color #fcfcfc / #121212, apple-touch-icon from the approved shield J, in-app back buttons in standalone mode.
**Audit viewports:** 390×844 (iPhone), 412×915 (Fold folded) + 673×841 (unfolded), 1024×1366 (iPad), 1440×900 (Mac). The full matrix is in RESPONSIVE-SYSTEM §9.

## 9. Apple platform notes (native Mac app, menu bar, widgets, Control Center)
- Follow the HIG (https://developer.apple.com/design/human-interface-guidelines): standard window chrome and toolbar, sidebar `NavigationSplitView`, Settings scene, ⌘ shortcuts, and system materials (`.regularMaterial`) instead of custom blur.
- Map tokens to SwiftUI: accent becomes `AccentColor` #1680f3, text tiers become `.primary/.secondary/.tertiary`, radii 8/12/16/22, text styles the macOS scale (body 13). Generate them from the shared tokens (`tokens/jaeger-tokens.json`), not by hand.
- **Menu bar** (`MenuBarExtra`): status glyph (SF Symbol, template rendering), a short status list, approvals count, Open Jaeger. No settings in the menu.
- **WidgetKit**: systemSmall/Medium/Large = S/M/L cards with the same snapshot JSON as `/v1/widgets/snapshot`. Use the system container shape and support `.accented`/tinted rendering via `widgetAccentable`. Tapping deep-links `jaeger://…`; buttons are App Intents with `requestConfirmation`.
- **Control Center** (`ControlWidgetButton`/`ControlWidgetToggle`): one action each, confirm except the e-stop, SF Symbol + short label.
- PWA limits: Safari web apps can't add WidgetKit or Control Center widgets, so these ship with the native app.

## 10. Do's and don'ts
Do: use tokens only, use one accent, give every data region all three states, confirm risky actions, use real data, check axe and the 4 viewports before calling UI done, and use Light *and* Dark.
Don't: hard-code hex or px outside the token files, add new greys or fonts, use purple-gradient or "AI slop" hero styles, show emoji as icons, build hover-only controls, use `100vh`, open a modal from a modal, or invent copyrighted character art (leave existing art alone; note it in docs only).

## 11. Agent prompt guide
"Build this in Jaeger's design system: read DESIGN.md, use `--jg-*` tokens and `src/unified/ui.tsx` primitives, system font, the in-repo icon set, the 8pt spacing and radius scale, and container-query size classes. Give it loading, empty and error states. Verify at 390/412/1024/1440 in light and dark with Playwright and axe, then run the `ux-audit` skill." Pair with the `frontend-design` and `ui-ux-pro-max` skills for direction, but **this file overrides them** where they conflict (for example, no Tailwind and no new fonts).

## References

Merged 2026-11-11 from the former `jaeger_ai/interfaces/ui/DESIGN.md`; this file is the single design authority.

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
