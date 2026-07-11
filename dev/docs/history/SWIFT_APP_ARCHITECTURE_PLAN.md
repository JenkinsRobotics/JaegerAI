# JROS Swift-first app architecture — the plan (FOR APPROVAL)

**Status: PROPOSED 2026-07-04 — no implementation until the operator approves.**
(Standing rule: daemon-architecture changes need an explicit plan + approval.)

**Context:** JROS is going Swift-first — the Swift app becomes the primary UI,
native Mac look/feel, app icon, a baseline that grows for years. JROS's end
goal stays the anchor: **an agent for real-world hardware-enabled robotics.**
The archived four-tier daemon brief (dev/docs/archive/JROS_DAEMON_ARCH_BRIEF.md)
is re-opened by this decision, because Swift-first changes the process math.

---

## 1. Assessment of today's Swift ↔ Python integration

### What's right (keep)
- **The boundary is in the correct place.** Swift owns presentation; Python owns
  agent state, tools, memory, skills. Neither side duplicates the other's logic
  (Python-side settings mutation is the right call).
- **The transport concept is right.** A local NDJSON bridge is simple,
  debuggable, and — critically for robotics — **portable to Linux**, unlike XPC.
- **The surface mix is pragmatic**: MenuBarExtra companion, NSWindowController
  windows, SwiftUI content. Splash + shared SettingsStore + character card grid
  are the right UX direction.
- The persona output filter (station 3) already flows through `run_for_voice`,
  so the Swift chat gets the character voice with no extra wiring.

### What's prototype-grade (verified findings — concurring with the review)
| # | Finding | Verified at |
|---|---|---|
| 1 | **BridgeProcess can hang forever** — `readyCont` has no timeout; pending `resultConts` are never resumed on termination | BridgeProcess.swift:65-93, 149 |
| 2 | **UI startup coupled to full model boot** — bridge emits `ready` only after `boot_for_tui` (≈40s model load) | bridge.py:216→262 |
| 3 | **No connection state machine** — `connect()` flips a bool; double-connect possible; child death never updates `isConnected` | AgentBridge.swift:48-59 |
| 4 | **Untyped protocol** — Swift parses dynamic dicts; no protocol version/capabilities in `ready`; a Python frame change degrades the UI silently | protocol.py / AgentStatus |
| 5 | **Settings errors invisible** — decode/bridge failures become empty UI; saves don't refresh detail | SettingsStore.swift:115 |
| 6 | **Permissions non-interactive** — bridge auto-denies; real tool flows will fail arbitrarily from the UI | bridge.py permission path |
| 7 | **Session isolation incomplete** — ChatViewModel has a sessionKey; `sendChat(text:)` never passes it; everything collapses into one Python session | AgentBridge.swift:103 |
| 8 | **launch.py is a dev script** — `swift build -c release` on every launch | launch.py:749 |

### Additional findings (mine)
| # | Finding | Impact |
|---|---|---|
| 9 | **The bridge child SIGABRTs on every clean exit** — bridge.py lacks the F1 `os._exit` mitigation (added to main.py + bench.py 2026-07-04), so ggml's Metal teardown aborts the process. Swift cannot distinguish crash from clean quit → any death-detection logic is built on noise | Must fix before finding #3's state machine means anything |
| 10 | **Instance-lock semantics are not part of the contract** — the bridge boots via `boot_for_tui`, inheriting the single-instance lock; a second UI (or a UI next to a running TUI) hits lock conflicts with no protocol-level story | Needs an explicit `busy/locked` ready-failure frame |
| 11 | **Zero Swift-side tests** — no XCTest target, no shared protocol fixtures; the boundary has no regression net | Industrial baseline requires it |
| 12 | **No packaging pipeline** — SPM executable only: no .app bundle, Info.plist, icon, signing, notarization, or update story. (`jaeger launcher install` makes a CLI stub .app — different thing) | The "native Mac app" ask is this pipeline |

**Verdict (concurring):** right architecture, prototype-grade lifecycle. The
boundary must be hardened into a product contract before anything is built on it.

---

## 2. THE DECISION: daemon or not

**Recommendation: YES — a persistent core service, staged, and lighter than the
four-tier brief.** Named going forward: **JROS Core** (the Python agent) +
**Jaeger Shell** (the Swift app).

### Why the 2026-06-14 fused-mode decision no longer holds
Fused mode was chosen when the TUI was the primary surface — UI and agent
shared one process, so "close it and it dies" was coherent. **Swift-first
already breaks fusion**: the UI and the agent are two processes today; the only
question left is *who owns the core's lifetime*. Right now the answer is "the
UI does" (child process), which is the wrong answer for this product:

1. **Robotics (the anchor):** the brain must run headless — cron, Deep Think,
   schedules, sensors, and eventually motors. A robot cannot lose its mind
   because someone closed a window. UI = optional attachment to a running
   agent. That is a daemon by definition.
2. **Native-Mac grounding:** this is exactly how serious Mac agents ship —
   Ollama, Docker Desktop, Tailscale: a background service + an app/menu-bar
   shell that attaches. "Native feel" for an assistant means the menu-bar
   presence persists and windows come and go.
3. **Warmup tax:** ~40s model boot per app-open is unacceptable; a persistent
   core pays it once.
4. **Session persistence** (backlogged, explicitly blocked on this decision)
   falls out of it: the core owns sessions.db and outlives the shell.

### What we are NOT deciding (deferred, per the brief's own advice)
- **Tier 2 subagent processes** — `delegate_task` (in-process) covers today's
  need; process isolation for subagents is a later, separate decision.
- **Tier 3 hardware-node supervision** — arrives WITH JP01 hardware (the
  format-0.1 Supervisor + `[[node]]` manifests are the pattern; Mochi is the
  reference). The brief stays archived until then.
- The four-tier brief's full IPC redesign. NDJSON stays.

### Transport decision
**Keep NDJSON, add a Unix-domain-socket transport beside stdio.** Same frames,
two carriers: stdio (dev/child mode) and socket (attach mode). XPC is rejected:
macOS-only, and JROS cores will run on Linux robots. The protocol gets a
version + capability list in `ready` (v1) so shell/core skew fails loudly.

---

## 3. Target architecture

```
                     ┌────────────────────────────────────────────┐
                     │  JROS CORE (python) — launchd LaunchAgent   │
                     │  com.jenkinsrobotics.jaeger.core            │
                     │  agent loop · tools · memory · skills ·     │
                     │  cron · Deep Think · persona filter         │
                     │  listens: unix socket per instance          │
                     └────────▲───────────────▲───────────────────┘
                     NDJSON v1 │               │ NDJSON v1
                 (attach-or-spawn)             │
                  ┌───────────┴─────┐   ┌──────┴──────────┐
                  │ JAEGER SHELL    │   │ jaeger CLI /    │
                  │ (Swift .app)    │   │ TUI / voice     │
                  │ menu bar · chat │   │ (unchanged,     │
                  │ settings · orb  │   │  can attach)    │
                  └─────────────────┘   └─────────────────┘
   Later (with JP01):  core supervises hardware nodes (Tier 3, Mochi pattern)
```

Lifetime semantics (native-Mac):
- Launching the Shell attaches to a running core, or spawns one if absent.
- Closing windows never kills the core. Quitting the Shell (Cmd-Q) leaves the
  core running by default (menu-bar apps' convention); **"Quit Jaeger
  Completely"** stops both. A robot deployment runs the core with no shell.
- Login item via `SMAppService`; core managed by launchd (`KeepAlive` for
  crash restart).

---

## 4. Phases (each gated, each shippable)

### Phase 1 — Harden the boundary (no daemon yet; required regardless)
The review's top-3 + my #9/#10, in child-process mode:
1. **BridgeProcess cannot hang**: ready/request/turn timeouts; on termination
   resume every pending continuation with a typed failure; clear pipe handlers.
2. **AgentBridge state machine**: `disconnected → connecting → ready → failed /
   terminated`; single in-flight connect; child death drives published state.
3. **Fast-ready split**: bridge emits `ready` (protocol v1, capabilities,
   instance) BEFORE model boot, then streams `agent_state: booting → warm →
   ready`. Settings/config queries work immediately; chat gates on agent-ready.
   (bridge.py boots the agent AFTER the handshake, off-thread.)
4. **bridge.py F1 fix** (`os._exit` after clean teardown) so exit codes mean
   something; termination frames carry a reason.
5. **Typed protocol v1**: versioned Codable frame enums on Swift; version +
   capabilities in `ready`; shared JSON fixtures tested from BOTH sides
   (pytest + XCTest against the same fixture files); lock-conflict frame (#10).
6. **Session keys through `sendChat`** (+ Python honors them — sessions.db
   already does).
7. **Visible errors**: SettingsStore per-section load/error state; saves
   refresh detail.
8. **Interactive permissions**: bridge forwards permission requests as frames;
   Swift shows an approval sheet; response frame resolves the confirmation
   provider (the Event pattern already exists on the Python side).

### Phase 2 — Native app packaging
- Real `.app` bundle: Xcode project (or SPM + bundler) with Info.plist, asset
  catalog **app icon**, proper bundle ID (`com.jenkinsrobotics.jaeger`).
- **Developer ID signing + notarization**; zip/DMG distribution; Sparkle (or
  `jaeger update`-driven) app updates later.
- `launch.py --dev` keeps build-on-launch as the DEV path; the packaged app
  runs its bundled binary and spawns/attaches to the core. `jaeger` CLI
  unchanged and headless-capable (robot mode).
- CI: swift build + XCTest + SwiftLint/swift-format alongside pytest.

### Phase 3 — The lifetime split (the daemon proper)
- Unix-socket transport beside stdio (same NDJSON v1); socket path per
  instance under the instance dir.
- launchd LaunchAgent plist install via `jaeger core install` (mirrors the
  existing `jaeger launcher install` pattern); `KeepAlive` crash restart;
  `jaeger core start|stop|status`.
- Shell attach-or-spawn; "Quit Completely" menu item; login item toggle.
- Update coordination: `jaeger update` stops core, swaps, restarts; shell
  reconnects (state machine already handles it from Phase 1).
- Session continuity across shell restarts (sessions.db; the cross-restart
  digest already exists).

### Phase 4 — Hardware tier (WITH JP01; re-opens the archived brief's Tier 3)
- Core supervises hardware nodes (ON/OFF/RESTART/STATUS, health broadcasts,
  crash policy) via the format-0.1 Supervisor + `[[node]]` manifests.
- Node telemetry → InfluxDB (already a 0.7 note). Real-time nodes (motor PID)
  get process isolation exactly as the brief argued — that's when its four-tier
  framing comes back off the shelf.

---

## 5. Failure modes designed for
| Failure | Answer |
|---|---|
| Shell/core version skew | proto version + capabilities in `ready`; shell refuses politely + offers update |
| Orphan core | launchd owns it; socket + pidfile per instance; `jaeger core status` |
| Core crash mid-turn | launchd restarts; shell state machine → `terminated` → auto-reattach; turn reported failed honestly |
| Two shells / shell + TUI | socket is multi-client by design later; Phase 1 = lock-conflict frame, one owner |
| Update while running | explicit stop-swap-restart choreography in `jaeger update` |
| Robot (no GUI) | core runs headless under launchd/systemd; nothing in core may import AppKit — enforced by keeping ALL UI in Swift |

## 6. Industrial standards checklist (the "sustain us long term" list)
- Typed, versioned protocol with cross-language fixture tests (the contract IS
  the product boundary)
- Lifecycle state machines, never booleans; timeouts on every await
- Structured logging both sides (os.Logger / unified logging on Swift; the
  existing audit + logs on Python), correlated by request id
- CI gates: pytest + XCTest + integrity/bench gates already in place
- Signing, notarization, versioned releases, update path
- No AppKit in core / no agent logic in Swift — enforced review rule

## 7. Out of scope (explicit)
- Subagent process isolation (Tier 2), MCP process model
- Cross-machine / network attachment (socket stays local-only for now)
- Windows/Linux shells (core stays portable; shell is macOS)

## 8. Approval gates
- **Gate A (this doc):** direction — Swift-first shell + persistent JROS Core,
  staged as Phases 1→4. Includes the daemon YES decision (Phase 3).
- **Gate B (after Phase 1):** review hardened boundary before packaging.
- **Gate C (before Phase 3):** confirm launchd/core split UX before it ships.
