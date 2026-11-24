# Build-script spec: `build-tokens`

**Input:** `tokens/jaeger-tokens.json` (W3C Design Tokens format). A reference implementation is in `build/build_tokens.py` (Python 3, stdlib only). It's verified: 648 contrast checks with 0 fails, and the Swift output passes `swiftc -typecheck`. The package may port it to `build-tokens.mjs`, but the outputs must match it byte for byte.

**Resolve rule:** `color.<mode>` ← `feel.<feel>.<mode>` ← `brand.aether.<mode>` (if `data-brand="aether"`). The last writer wins, and a missing role falls back to `jaeger`.

**Outputs** (in `dist/`; samples are in `build/out/`):

| File | Content | Consumers |
|---|---|---|
| `jaeger.css` | `--jg-*` on `:root`, `[data-mode]`, a `prefers-color-scheme` fallback, `[data-feel][data-mode]`, `[data-surface="web"]` (body 14px), `[data-brand="aether"]`, and reduced motion | canonical UI, web UI, jaeger-chat-ui web/native hosts |
| `jaeger-vscode-map.css` | 104 `--vscode-*: var(--jg-*)` (the color, font and radius subset of the 143 in `THEME-VARS.md`; sizes and spacing stay in `size-defaults.css`) | jaeger-chat-ui **web/native hosts**, and VS Code only when feel ≠ `vscode` |
| `aether.css` | legacy `--aether-*` → `--jg-*` aliases (removed in v1.1) | AetherStudio, vendored aether-ui |
| `JaegerTokens.swift` | `JaegerFeel` enum, dynamic `NSColor(name:)` per role (light/dark × feel), spacing, radius, body 13 | macos-shell |
| `theme.py` | TUI accent, ok, warn, error | `interfaces/tui/theme.py` |
| `contrast-report.json` | every resolved feel × mode, aether, and tints | CI |

**CI gates:**
- The build exits non-zero on any WCAG AA fail. That means text tiers, accent-text, status and info at ≥4.5 on surface, sidebar, raised and inset; faint, border-strong and focus at ≥3.0; and on-accent at ≥4.5 on accent and accent-hover.
- It fails if a generated file has been hand-edited (header hash).
- It fails if a vendored copy's sha256 ≠ the pinned release.
- `check-theme-literals` fails on new hex literals outside the generated files.
