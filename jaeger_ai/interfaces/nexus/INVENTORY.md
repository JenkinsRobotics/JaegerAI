# Swift Mac app → NexusUI app: element inventory

The Swift app (`jaeger_ai/interfaces/macos-shell`, 46 sources + 20 tests) stays as it is. So does the WebUI
(`jaeger_ai/interfaces/ui`, :8790). This NexusUI app is added beside them and talks to the Gateway (:33418).

Run it: `python -m jaeger_ai.interfaces.nexus` (its own pywebview window) or `--browser` (the same screen on :8795).
The screen source is `web/` (React + TypeScript + Vite, copied from Jaeger Omni's screen). It builds into
`~/.cache/jaeger/nexus-ui/dist`, outside the repo.

Key:
- **✅ checked** = exercised on 2026-11-27 against the dev Gateway on this Mac.
- **◐ built** = written and wired, not exercised (reason given).
- **≠ differs** = no exact equivalent; the closest counterpart is given.

Where things live: **Screen** = a page in the left page rail (Chat, Status & stack, Tasks, Droid, Mac, Activity,
Settings). **Menu** = the NexusUI menu-bar item (`native.py`). **Server** = `serve.py` / `shell.py` / `gateway.py`.

## Main window (JaegerShellApplication.swift)

| Swift element | NexusUI counterpart | State |
|---|---|---|
| Main window (WKWebView of the WebUI) | Own pywebview window, `__main__.run_window`. It shows this app's own screen; "Main screen (WebUI) ↗" in the rail opens the WebUI | ✅ checked |
| Close button hides instead of quitting | `events.closing` hides the window; Quit is in the Menu | ◐ built |
| "Main screen is not available" page | Header pill shows "Connecting to the Gateway…"; Agent panel shows Why. The server answers 503 when the screen is not built | ◐ built (offline state not tested) |
| App menu Start / Restart / Stop Jaeger… | Status & stack page + Menu, with a confirm step (`jaeger stack up/restart/down --json`) | ◐ built (not run: it would restart the live Gateway) |
| Quit (⌘Q) | Menu › Quit Jaeger (NexusUI); pywebview's own app menu | ◐ built |
| Edit menu (undo, cut, copy, paste, select all) | pywebview's standard macOS Edit menu | ◐ built |
| View › Reload (⌘R) | ⌘R in the window; Reload on the Status page and in the Menu | ◐ built |
| Global hotkey ⌃⌥Space | `native.Hotkey`. Default ⌃⌥J so it does not clash with the Swift app; ⌃⌥Space is selectable in Settings | ◐ built (installed, key not pressed; other apps' keys need Accessibility) |
| `jaeger://` URL handler | `--open jaeger://…` and POST `/shell/open`, same rules as JaegerDeepLink (its test cases are `shell.py`'s self-check). The OS scheme stays with the Swift app (≠) | ✅ checked |
| Notification click → conversation or inbox | One-slot pending mailbox (`/shell/pending`) opens Chat or Tasks | ◐ built (osascript notifications cannot carry a click target: ≠) |
| Dock reopen | pywebview's default | ◐ built |
| Activation policy (Dock + menu bar) | Dock icon (Python) + menu-bar item | ✅ checked (menu-bar item); ◐ Dock icon not looked at |
| Shell Pause / Resume | Settings checkbox, Status page and Menu; turns the hotkey off | ◐ built |
| openDroidView | Droid page › Open Droid View (WebUI `/droid`) | ◐ built |
| NSOpenPanel for file inputs | WebKit's file picker (composer ＋) | ◐ built |
| NSSavePanel for downloads | ≠ pywebview handles downloads itself; the screen has no downloads | ≠ differs |
| Mic/camera permission only for the loopback page | `window.grant_media` (copied from Omni): grants only 127.0.0.1/localhost | ◐ built |
| Launch at Login (SMAppService) | Opt-in LaunchAgent `com.jenkinsrobotics.JaegerAI.nexus` (Settings + Menu) | ◐ built (not switched on: it is persistent) |
| Alert "Lifecycle ownership was not acquired" | ≠ no lifecycle lease in this app (it owns no stack processes) | ≠ differs |
| Appearance observer | Aether dark tokens (copied) | ≠ dark only |

## Menu-bar item (StatusItemController.swift)

| Swift element | NexusUI counterpart | State |
|---|---|---|
| Icon running / off | SF Symbol `circle.hexagongrid(.fill)`, template image | ✅ checked (item present, tooltip "Jaeger (NexusUI)") |
| Progress ring / unread dot | Symbol switches to `arrow.triangle.2.circlepath` while tasks run | ◐ built (no live-tasks route, see Tasks) |
| Tooltip (paused / N tasks / Offline) | Same text in `Menu.refresh` | ✅ checked |
| Left click toggles the window; right / ⌃-click opens the menu | `Menu.clicked_` | ◐ built |
| Health timer (10 s): WebUI `/` + Gateway `/health` | `shell.Monitors._health_loop` | ✅ checked |
| Show / Hide Jaeger | Menu; Status page › Show Jaeger | ◐ built |
| Live task section | Menu + Tasks page | ✅ checked (shows "route not available") |
| "Main screen: …", "Gateway: …", "Shell: …" status lines | Menu + Status page | ✅ checked |
| Pause / Resume Jaeger Shell | Menu + Status page + Settings | ◐ built |
| Start / Restart / Stop Jaeger stack… | Menu (NSAlert confirm) + Status page (inline confirm) | ◐ built |
| Launch at Login (checkmark) | Menu + Settings | ◐ built |
| Reload | Menu + Status page | ◐ built |
| Open in Browser | Menu + Status page | ◐ built |
| Quit JaegerAI | Menu › Quit Jaeger (NexusUI) | ◐ built |

## Droid (DroidMenuController.swift)

| Swift element | NexusUI counterpart | State |
|---|---|---|
| Droid state line (+ E-Stop) | Droid page + Menu, from GET `/v1/droid/status` (`awake`, `camera`, `estop_latched`) | ✅ checked ("Droid: Awake (Camera Ready)") |
| Sense line (gimbal · pan · tilt) | Shown when a gimbal-capable camera is listed | ◐ built (no gimbal attached) |
| Turn On / Off Droid Mode | POST `/v1/droid/wake` / `sleep`, same enable rules | ◐ built (not pressed: it moves the camera) |
| Park Camera Now (Privacy) | POST `/v1/droid/sleep` with reason `…_park` | ◐ built |
| Center Camera | POST `/v1/embodiment/droid/act {action:"center"}` | ◐ built |
| Open Droid View | Opens WebUI `/droid` | ◐ built |
| Permissions › Microphone / Camera | Settings › Permissions (AVFoundation, read only) + Menu submenu; click opens System Settings | ✅ checked (Microphone: Allowed, Camera: Not asked) |
| Refresh Droid Peripherals | GET `/v1/droid/devices?refresh=1` | ◐ built |

## Mac (MacControlMenuController.swift)

| Swift element | NexusUI counterpart | State |
|---|---|---|
| Lock Mac | `SACLockScreenImmediate`, falling back to `pmset displaysleepnow` (same as Swift); confirm on the screen | ◐ built (not pressed) |
| Turn Display Off | `pmset displaysleepnow` | ◐ built (not pressed) |
| Mac Status… | Mac page + Menu alert: uptime, disk free, battery | ✅ checked |

## Monitors and notifications (LiveTaskMonitor.swift, AgentStatusMonitor.swift)

| Swift element | NexusUI counterpart | State |
|---|---|---|
| Live task poller (1.5 s, Bearer token) | `Monitors._task_loop`, same token lookup (`JAEGER_CALLER_TOKEN`, then `caller_tokens/menubar.token`); stops on 404 like Swift | ✅ checked. The Gateway on master has **no** `/v1/live/tasks`, so both apps show none |
| "Working: …" / "Done: / Failed: …" notifications | `Monitors._notify` via `osascript` | ✅ checked (test notification) / ◐ task path needs the route |
| AgentStatusMonitor (never started in Swift) | Header pill + Agent panel, from the Gateway event stream and `/health` | ✅ checked |

## Bridge (NativeBridge.swift), voice and chrome

| Swift element | NexusUI counterpart | State |
|---|---|---|
| Chat through the WebUI | Chat page through the Gateway: POST `/v1/sessions/{sid}/runs`, SSE `/v1/sessions/{sid}/events`, history from `/messages?page=latest` | ✅ checked (window and browser; replies streamed) |
| notify (JS → native) | Settings › Send a test notification; `/shell/action notify.*` | ✅ checked |
| window.setPinned | Settings › Keep the window on top (`window.on_top`) | ◐ built |
| clipboard.read / ClipboardPreview (100 kB, explicit read) | Composer › Clipboard: reads only on click, shows a preview, refuses over 100 kB | ◐ built |
| clipboard.write | Reply › Copy uses `pbcopy` | ◐ built |
| files.pick | Composer ＋: text files go into the message, sound clips go to hearing | ◐ built |
| history.consent alert | Settings checkbox, stored in `<state>/nexus-ui.json` | ◐ built |
| computer.status / computer.settings | Settings › Permissions: Accessibility + Screen Recording from `jaeger_macos.probe_tcc_status`, with buttons that open System Settings | ✅ checked (Screen Recording: Allowed) |
| link.open / open.external / app.info / stack.status | Rail link and Status page; the header pill shows the Gateway's model | ✅ checked (pill) / ◐ links not clicked |
| Voice: mic + Apple speech-to-text | Mic records a clip → Jaeger Agent's hearing (jaeger-whisper-stt 0.14.0 through `voice_worker.py`), else the Gateway's `/v1/droid/transcribe`. Half duplex: the mic stays shut while she speaks | ✅ checked in the worker (its own speech heard back correctly in 534 ms) / ◐ the window's Mic button not pressed |
| Voice: AVSpeech TTS (tts.speak) | The avatar speaks every reply in Jaeger Agent's voice (jaeger-kokoro-tts 0.14.0, af_heart, MLX; `[laugh]` plays her recorded laugh). Reply › Read aloud keeps Apple speech | ✅ checked (window: "state speaking", no error, mouth moving) |
| NativeChrome / StudioWindowChrome | pywebview window with Aether dark background; Aether tokens copied into `web/src/aether-tokens.css` | ✅ checked |
| ControllerPill (never instantiated in Swift) | "Quick Ask…" in the Menu opens a frameless always-on-top 520×240 window (`#pill`): ↵ sends, Esc closes | ◐ built |
| CheckPrompt / VerifyBridge / Snapshot / lease self-checks | `python -m jaeger_ai.interfaces.nexus.shell` and `.native` self-checks; `npm test` in `web/` (10 tests) | ✅ checked |
| LeaseBeat | ≠ no lease (this app owns no stack processes) | ≠ differs |
