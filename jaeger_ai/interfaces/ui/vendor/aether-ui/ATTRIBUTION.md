# Attribution

This directory is a **vendored copy** of `@aether/ui` from AetherStudio.

- **Source repo:** `~/GitHub/AetherStudio` (Matthew Jenkins), path `core/ui/`
- **Source commit:** `ece0209` ("Update")
- **Copied:** 2026-10-17 for the Jaeger UI rebuild (plan step 3), by the Agents View bot
- **License:** Apache License 2.0. See `LICENSE`, copied from the AetherStudio repo root. AetherStudio ships no NOTICE file.

Assets are vendored next to this directory, in `../assets/`, so the widgets' relative `../../assets/...` imports resolve:
- `icons/`, `themes/` (`aether-default.json`), `licenses/` (from `core/assets/`)
- `branding/apps/*.svg` (PNGs were not copied)

## Modifications (Apache-2.0 §4(b))
- Excluded: `gallery/`, `Launcher/` (hard-coded port 8792), `native/` (StudioWindowChrome now lives in `interfaces/macos-shell`), `node_modules/`, `dist/`.
- Removed `ViewportCanvas*` and `ViewportNavigationCube*`, since they are three.js and CAD-only. Their exports were removed from `src/index.ts`. `src/WorkspaceShell.test.tsx` was removed because it imports `ViewportCanvas`.
- `package.json`: removed the `three`, `@types/three` and `@aether/core` devDependencies and the gallery/build scripts. Removed `package-lock.json` and `vite.config.ts` (gallery + CAD engine aliases). `tsconfig.json` now includes only `src`.
- Widget sources, `tokens/tokens.css`, `tokens/home.css` and `src/widgets.css` are otherwise **unmodified**.
