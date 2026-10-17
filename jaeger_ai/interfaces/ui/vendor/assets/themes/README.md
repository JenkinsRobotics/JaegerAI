# Themes

A theme is one JSON manifest in this directory shipping **both modes**:

```
{ "id": "my-theme", "name": "My Theme",
  "modes": { "dark": { "color-…": … }, "light": { … } },
  "geometry": { … }, "font": { … } }
```

- `aether-default.json` is the built-in theme (generates `:root` +
  `.aether-light-theme` in `core/ui/tokens/tokens.css`).
- Every other manifest here emits side by side as `.aether-theme-<id>`
  when you run `node dev/build-theme-css.mjs`.
- Hot install without a build: `installAetherTheme(manifest)` +
  `setAetherTheme(id)` from `@aether/ui`. Selection persists per device
  and syncs across tabs; System/Light/Dark works inside every theme.
