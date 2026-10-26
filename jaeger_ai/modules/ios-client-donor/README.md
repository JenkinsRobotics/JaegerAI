# ios-client-donor — DONOR REFERENCE ONLY, NOT a Jaeger iOS app, NOT yet wired

Job: a native iPhone client for Jaeger is a gap — Jaeger today has WebUI :8790 (reachable over Tailscale Serve, see ui-remote-access) and a Mac menu bar shell, but NO native iOS app in the repo. This module records a donor reference for building one, it does NOT add a Jaeger iOS app.

Source, NOT copied into this module:
- Desktop "Ai  work " / JaegerAI_Archive/apps_ios/ — README.md 9,794 bytes, HermesMobile/ (ContentView.swift, HermesMobileApp.swift, AppIntents/, Auth/, Config/, Features/, LiveActivities/, Models/, Networking/, Persistence/, Resources/), HermesLiveActivityWidget/, HermesShareExtension/, WatchApp/, WatchTests/, HermesMobileTests/, scripts/, Config/, HermesMobile.xcodeproj.
- Its own README classification, verbatim in substance: HISTORICAL / DONOR DOCUMENTATION. This tree is an imported Hermes-branded iOS client. It currently targets Hermes WebUI endpoints and branding, NOT the Jaeger Gateway, and is NOT the qualified Jaeger phone/field client.
- Features in that donor, as a design checklist only: native SwiftUI iOS 18+, chat with streaming + thinking/tool-call detail, steer/stop a run, sessions browse/search/resume + offline cached sessions, model/provider switching, profiles/projects, tasks (cron jobs), skills browse/search, workspace browser, memory/insights read-only panels, Live Activity, Watch app, Share extension, AppIntents.
- Also in that folder: OnboardingTailscalePage.swift (3,151 bytes) — iOS onboarding for Tailscale, useful as UX reference for the WebUI-over-Tailscale path, NOT as Jaeger auth (Tailscale identity does not make API endpoints credential-free; remote_access token + trusted networks still apply).

What must change before ANY code from this donor is used in Jaeger (IDE agent):
- Re-target every endpoint from Hermes WebUI to Jaeger Gateway :33418 / WebUI :8790, with Jaeger auth (caller token, not Hermes Keychain service ai.jaeger.gateway.caller as-is).
- Rebrand Hermes -> Jaeger, remove Hermes/Hermex branding, check license for the donor tree (no LICENSE file was listed at the apps_ios top level in this audit — do NOT copy code until license is confirmed).
- Do NOT present this donor as a Jaeger iOS app, and do NOT add it as a second iOS client alongside a future Jaeger iOS app. One iOS client only, built from this reference, not copied wholesale.

Test to run when code-run is available: build a Jaeger-targeted iOS client from this reference, open a session, send a turn, approve/deny from the phone, off-tailnet is refused, token is required — same tests as ui-remote-access, on a native app.
