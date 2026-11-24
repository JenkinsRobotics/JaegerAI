# SPEC-02: IDE chat (for the Jaeger IDE Chat bot)

## Scope
The `jaeger-chat` repo (`packages/jaeger-chat-ui`, `jaeger-tab` extension, branch `jaeger-tab` 0910505) and the in-repo IDE extension `JaegerAI/jaeger_ai/interfaces/ide`. Both adopt `--jg-*`, a feel switch, the avatar, the header icon, and the `jaeger` defaults.

## Theming model
Components keep consuming `var(--vscode-*)`, which is the existing contract in `THEME-VARS.md`. The mapping layer decides where the values come from:
- **web/native hosts:** load `jaeger.css` + `jaeger-vscode-map.css`, so the `--vscode-*` vars resolve to `--jg-*`.
- **VS Code host, feel = `vscode`:** load neither, and the host-injected `--vscode-*` vars stand as the fallback.
- **VS Code host, any other feel (default `jaeger`):** load both, scoped to `.jaeger-chat-host[data-feel]:not([data-feel="vscode"])`. Wherever a `--jg-*` value is missing, the host `--vscode-*` value stays.

## Files
- `packages/jaeger-chat-ui/src/theme/jaeger-base.css`: import the vendored `jaeger.css` and the scoped `jaeger-vscode-map.css`. Keep `size-defaults.css` for sizes and spacing.
- `src/host.ts` (:167 `kind`, :205 `onThemeChanged`): add `feel`, `avatar`, `onFeelChanged?`, `onAvatarChanged?`.
- `src/mount.ts` (:184-193 theme observer, :660 root classes): set `data-feel` / `data-mode` on the mount root, and re-sync on host events. Code-block themes follow `data-mode`.
- `src/hosts/webHost.ts`, `src/hosts/nativeHost.ts`: pass mode and feel from the Mac bridge (`appearance.changed`, `feel.changed`, `avatar.changed`).
- `src/streamStyle.ts`: add the `jaeger` preset (adaptive 20–40 words/s, 150ms out-quint fade, live fences, dots indicator) and make it the default instead of `vscode`. Export it for the Mac UI (SPEC-01).
- Assistant avatar in the chat list: `avatar-bronze-face-{32,64}.png` bundled under `jaeger-tab/media/avatar/`, and passed to the webview as a webview URI. A custom avatar arrives as a data URI.
- `jaeger-tab/package.json`:
  - `:9` `icon`: `media/jaeger.png` → `media/shield-blue-128.png` (Marketplace, static).
  - `:27`, `:37` activity bar: `media/jaeger-activity.svg` → monochrome `shield-template.svg` (currentColor, 24-unit). This is **static**, so it can't follow `appearance.icon`.
  - `:287` `jaeger.chat.streamStyle`: default `"vscode"` → `"jaeger"`.
  - Add `jaeger.appearance.feel` (enum of 7, default `jaeger`), `jaeger.appearance.avatar` (default `bronze-helmet`) and `jaeger.appearance.icon` (default `shield-blue`; header only).
- Webview header: a 16px icon from `appearance.icon` (shield-blue by default) plus the "Jaeger" title.
- `JaegerAI/jaeger_ai/interfaces/ide/package.json` `:7` → `media/shield-blue-128.png`. `:94` / `:113` → monochrome shield SVG. `extension.js:698` `LOGO` → shield SVG. `media/view.css` and `motion.css`: replace the fallbacks and the durations/easing with `var(--jg-*)` from the vendored `jaeger.css`.

## Acceptance criteria
- [ ] In VS Code with feel `vscode`, the panel is pixel-identical to today in Dark Modern, Light Modern and both high-contrast themes.
- [ ] With feel `jaeger` (default), the panel uses `--jg-*`. Switching the setting re-themes it live through `onDidChangeConfiguration`, with no reload.
- [ ] Each of the 7 feels × light/dark renders in the web host. A Playwright test reads computed colors and checks WCAG AA: text ≥4.5 and UI ≥3.0 on surface and inset, plus on-accent buttons.
- [ ] High-contrast VS Code themes always keep host values (map disabled under `.vscode-high-contrast*`).
- [ ] The assistant avatar is the bronze helmet face crop. A user avatar is unchanged.
- [ ] Marketplace and activity-bar icons are updated. The README notes that the activity-bar icon is static.
- [ ] `jaeger.chat.streamStyle` defaults to `jaeger`, and the Mac mirror is removed (SPEC-01).

## Out of scope
The `chatgpt`/`claude`/`gemini` feels, and VS Code core theming beyond the webview.
