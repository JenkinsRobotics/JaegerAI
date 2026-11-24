# SPEC-01: Mac app (for the Jaeger Mac App bot)

## Scope
`macos-shell` (JaegerShell, AppKit + WKWebView) and the canonical React UI it hosts. It adopts the tokens, adds light and dark mode for all native chrome, and adds the appearance settings, the Dock and menu-bar icons, the avatar, and propagation. The legacy SwiftUI app (`AetherTheme.swift`) was archived in 12235c56 (2026-10-19) and isn't revived.

## Files (JaegerAI `master` 2bfd47c5)
- `jaeger_ai/interfaces/macos-shell/Package.swift`: depend on the `jaeger-design-tokens` SwiftPM product, or vendor `JaegerTokens.swift` into `Sources/JaegerShellCore/Generated/`.
- `Sources/JaegerShellCore/NativeChromeContract.swift`, `Sources/JaegerShell/NativeChrome.swift`: window background, `underPageBackgroundColor` → `JaegerTokens.bg`. Delete the hex literals.
- `Sources/JaegerShell/JaegerShellApplication.swift` (~:243 `appearance.changed`): also handle `feel.changed`, `icon.changed` and `avatar.changed` from the UI. Apply the feel via `JaegerTokens.feel` and re-post `appearance.changed` on `NSApp.effectiveAppearance` KVO.
- `Sources/JaegerShellCore/Bridge.swift:328` `eventTypes`: add `feel.changed`, `icon.changed`, `avatar.changed` (both directions are documented in the header comment).
- `Sources/JaegerShell/StatusItemController.swift` (:20-44): load `shield-template-22` (@1x) / `-44` (@2x), with `image.isTemplate = true` and size 18×18pt. The off state is the same template at 40% alpha. **The template is always monochrome**, whatever the `appearance.icon` value.
- `Resources/`: add `shield-template-22.png`, `shield-template-44.png`, `shield-{blue,dark,light}-1024.png`, `avatar-bronze-{full,face}-{24,32,64,128,512,1024}.png`. Build `AppIcon.icns` from `shield-blue-1024.png` (sips + iconutil) and set `CFBundleIconFile` in `Resources/Info.plist`. Remove `jaeger_icon_22.png` / `jaeger_icon_off_22.png`.
- New `Sources/JaegerShell/AppIconController.swift`: on launch and on `icon.changed`, set `NSApplication.shared.applicationIconImage = NSImage(contentsOf:)` for the chosen built-in or `custom:<id>` (from `~/Library/Application Support/JaegerAI/icons/<id>/icon_1024.png`). `nil` restores the bundle icon.
- UI `jaeger_ai/interfaces/ui/src/main.tsx:2-5`: replace the `@aether/ui/tokens.css` + `./shell/tokens.jaeger.css` imports with the vendored `jaeger.css` (+ `aether.css` during migration). The native host sets `<html data-surface="native" data-mode data-feel>`.
- UI `src/settings/SettingsDialog.tsx`: add an **Appearance** panel (new `src/settings/AppearancePanel.tsx` plus a test). It has a Mode setting (System/Light/Dark), a Feel picker (7 swatch tiles), an App icon grid (`shield-blue`* / `shield-dark` / `shield-light` / `classic` / custom import), a Chat avatar grid (`bronze-helmet`* / `shield` / `classic` / custom), and a Sounds toggle (off). It persists to localStorage `jaeger.appearance.{mode,feel,icon,avatar,sounds}` and posts the bridge events.
- UI `src/chat/streamStyle.ts:83`: change `DEFAULT_STREAM_STYLE` from `"grok"` to `"jaeger"`. Import the presets from `jaeger-chat-ui` instead of the mirror (SPEC-02).
- UI chat message avatar component: assistant avatar = `avatar-bronze-face-{32|64}.png` at ≤32pt, `full-*` above, with a circle crop and `alt="Jaeger"`.

## Acceptance criteria
- [ ] Light and dark both render correctly, with no dark-only native surfaces. Toggling the System appearance updates chrome and web content within 1 frame, with no reload.
- [ ] A feel switch applies to the native background and the web UI with no reload. The choice persists across relaunch.
- [ ] The Dock shows shield-blue by default. Picking `shield-dark` updates the Dock at runtime. Finder and Launchpad show the bundle icon, which is a documented limit.
- [ ] The menu-bar icon is a template (it inverts with the menu-bar appearance). Its pixels are alpha-only (verified by `isTemplate` and an image check).
- [ ] The assistant avatar shows the bronze helmet face crop at 24/32pt and is crisp at @2x.
- [ ] New chats default to the `jaeger` stream style.
- [ ] **WCAG AA:** UI tests read computed `--jg-*` for each of the 7 feels × 2 modes, and text pairs are ≥4.5 and UI pairs ≥3.0 (matching `contrast-report.json`). There are no new hex literals in Swift or TSX.
- [ ] Reduced motion disables all `--jg-dur-*` transitions.

## Out of scope
Sound asset synthesis (cue ids only), the `chatgpt`/`claude`/`gemini` feels, rewriting the signed bundle icon at runtime, and the iOS/Watch targets.
