# Attribution — jaeger_ai/interfaces/macos-shell

Parts of this package are derived from **AetherStudio** by Jonathan Jenkins and Jenkins Robotics,
commit `ece0209`, licensed under the Apache License 2.0 (full text: `LICENSES/AetherStudio-Apache-2.0.txt`;
summary: `NOTICE`). Per Apache-2.0 §4(b), every modified file carries a prominent notice of the change in
its header, and the changes are listed here.

| Derived file (this package) | AetherStudio source @ ece0209 | Changes (Jenkins Robotics) |
|---|---|---|
| `Sources/JaegerShell/Aether/StudioWindowChrome.swift` | `core/ui/native/StudioWindowChrome.swift` | 2026-10-17: added `import JaegerShellCore`, `allowedOrigin`/`accepted`/`rejections`, and an origin check at the top of the `aetherWindow` message handler (main frame of the configured `http://127.0.0.1:<port>` origin only; rejections logged as `[shell][aetherWindow] rejected …`). Window styling, the user script and drag/double-click behaviour are unchanged. |
| `Sources/JaegerShell/JaegerShellApplication.swift` | `Aether CAD/Launcher/AetherCADApplication.swift` | 2026-10-17: renamed; engine spawn removed; loads the loopback Jaeger WebUI; loopback-only navigation + WKContentRuleList; inline not-running page; minimal main menu; menu-bar (accessory) app with status item; hide-on-close; `--verify-launch` / `--verify-bridge`; global hotkey; `jaeger` bridge. See the file header. |
| `Resources/Info.plist` | `Aether CAD/Launcher/Info.plist` | 2026-10-17: Jaeger identifiers (`com.jenkinsrobotics.JaegerAI.uirebuild`), dev-build flags, `LSUIElement`, `JaegerHotkey`, usage descriptions. |

Code ported from Jaeger's own `jaeger_ai/interfaces/swift` (same repository, Jenkins Robotics) is listed in `REUSE.md`.
