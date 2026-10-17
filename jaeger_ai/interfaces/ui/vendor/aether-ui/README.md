# Aether UI

The Aether family's shared design system: framework-neutral **design
tokens** plus a **one-widget-per-file React library** and a UIDev-style
**gallery**. Decision record:
`dev/docs/roadmap/UI_Framework_Decision.md`.

## Rules

- One widget per file, importable like a class: `import { Tree } from "@aether/ui"`.
- Widgets are product-free: data in, events out. Nothing here names a
  product concept or calls an engine verb — that is app code.
- Widget CSS consumes ONLY token variables. `tokens/tokens.json` is the
  single theming source; `tokens.css` mirrors it (native shells may
  generate their themes from the JSON).
- The baseline theme IS Aether CAD's current look (extracted 2026-08-01).
- The viewport stays imperative: mount renderers through
  `ViewportCanvas`, never re-render through React.

## Commands

```bash
npm install
npm run gallery     # UIDev-style widget gallery (Vite dev server)
npm test            # RTL behavior pins (vitest + jsdom)
npm run typecheck
npm run build       # static gallery build
```
