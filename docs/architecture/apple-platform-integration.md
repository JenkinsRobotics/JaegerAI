# Apple platform integration

Status: approved direction, implementation pending  
Date: 2026-09-15  
Targets: macOS 27, iOS 27, iPadOS 27, watchOS 27

## Outcome

Jaeger is one permanent agent. The Mac-hosted Jaeger Gateway remains its
always-on brain, memory, execution controller, and verification authority.
Apple devices are native ways to speak to it, supply permitted context, approve
actions, and follow work. Egypt is one mission for the same agent; it does not
create an Egypt-specific agent or orchestration stack.

An iPhone cannot be the sole 24/7 host. iOS schedules and limits background
execution. Jaeger's durable process therefore runs on a Mac or another
persistent host. The iPhone receives pushes, invokes App Intents, runs bounded
foreground/background work, and reconnects to durable Gateway sessions.

## Existing foundation

The repository already has:

- a native macOS SwiftUI application;
- App Intents for asking Jaeger, routines, stack status, profiles, and finance;
- Apple Speech recognition, speech synthesis, microphone, camera, and Vision
  seams;
- a typed REST and SSE client for Gateway sessions, turns, approvals, and
  handoffs;
- audited Mac tools for Calendar, Reminders, Notes, and Shortcuts;
- `JaegerAgentController` and `WorkLedger` as the completion authority for
  actionable work.

The current Apple client is macOS-only. Its Swift package requires macOS 14,
starts a local `jaeger bridge` child, and defaults to loopback URLs. The Gateway
also binds to loopback by default and has no client authentication suitable for
a phone. Those are deliberate desktop assumptions, not a mobile transport.

## Architecture

```text
                           persistent host
                     +-------------------------+
                     | Jaeger Gateway          |
                     | sessions + SSE          |
                     | controller + WorkLedger |
                     | tools + permissions     |
                     +------------+------------+
                                  |
                      authenticated, encrypted
                         Apple client protocol
                                  |
        +-------------------------+-------------------------+
        |                         |                         |
  macOS app                 iPhone/iPad app            Watch app
  local bridge + HTTP       chat + voice + camera      glance + approve
  full operator surface     intents + notifications    short commands
        |                         |
  Mac app automation        App Intents / Siri / Spotlight
  and local models          Shortcuts / Action button / widgets
                            Visual Intelligence / share extension
```

### One completion authority

All actionable requests enter a Gateway session. App Intents and on-device
models may classify, extract parameters, summarize, or ask for clarification.
They do not execute a second agent loop and never set `objective_verified`.
Only the existing controller and WorkLedger can declare the objective complete.

### One Apple transport client

Extract the platform-neutral Gateway HTTP, SSE, and wire types from the macOS
executable into a shared Swift client target under `clients/apple`. Both macOS
and iOS import that target. Keep the Unix child-process bridge in the macOS
interface because iOS cannot launch it.

The remote protocol must provide:

- device enrollment with revocable device identity;
- TLS transport over an operator-controlled private path;
- short-lived credentials stored in Keychain;
- per-device and per-capability authorization;
- idempotent turn submission and SSE resume cursors;
- explicit approval events for consequential actions;
- audit records that identify the requesting device and intent.

Do not widen the existing unauthenticated `127.0.0.1:8810` listener. Add an
authenticated ingress in front of it or a separately bound authenticated
Gateway listener. Keep the internal loopback behavior for the Mac client.

### iOS 27 intelligence

Use Apple's public integration surfaces:

- **App Intents and assistant schemas:** expose Jaeger actions to Siri, Apple
  Intelligence, Spotlight, Shortcuts, widgets, and the Action button.
- **Foundation Models:** use the system on-device model for private, bounded
  tasks such as intent classification, structured parameter extraction,
  summarization, and offline preparation. Use availability checks and a
  deterministic fallback because Apple Intelligence is device, language, and
  region dependent.
- **LanguageModel protocol:** optionally present Jaeger as a model provider
  inside Jaeger's own app architecture after the authenticated client is
  stable. This does not make Jaeger a system-wide Siri extension.
- **Visual Intelligence:** register semantic-content search and accept camera
  or screenshot context through the public App Intents query path.
- **Evaluations:** verify prompts and structured outputs against each supported
  Apple model version before release.

Apple's ChatGPT extension in Siri and Writing Tools is a system partnership,
not a public extension slot that an ordinary application can claim. Jaeger can
offer comparable user entry points through public App Intents, assistant
schemas, Visual Intelligence, Shortcuts, share extensions, and its own app.

## Apple application capabilities

| Surface | Native framework or seam | Initial behavior |
| --- | --- | --- |
| Siri, Spotlight, Shortcuts, Action button | App Intents, assistant schemas | Ask, run a routine, check status, approve or cancel work |
| Conversation | SwiftUI, shared Gateway client, SSE | Stream chronological work and final answers; resume sessions |
| Voice | Speech, AVFoundation | Push-to-talk first; local transcription when available |
| Camera and screenshots | Vision, Visual Intelligence, Photos picker | Send user-selected visual context to a Jaeger turn |
| Calendar and reminders | EventKit | Read with permission; preview and approve writes |
| Contacts | Contacts | Resolve people with least-privilege access |
| Maps and travel | MapKit, Core Location | Build plans and location-aware reminders with explicit permission |
| Photos and files | PhotoKit, PhotosPicker, FileImporter, share extension | User-selected ingestion; no silent library sweep |
| Health and fitness | HealthKit | Optional read-only summaries first; separate grants by data type |
| Home | HomeKit or Matter surfaces | Explicit device/action allowlists and confirmations |
| Notifications | UserNotifications, APNs | Completion, failure, approval, and scheduled-work alerts |
| At-a-glance control | WidgetKit, Live Activities, controls | Active job state and safe commands |
| Watch | WatchConnectivity, App Intents | Dictate, approve, cancel, and view status |

Notes and Mail do not offer general iOS automation equivalent to macOS
AppleScript. Use share sheets, compose flows, Shortcuts, or user-selected files
where Apple provides no public read/write API. Messages must use supported
compose or intent surfaces; Jaeger must not silently send personal messages.

## Delivery phases

### A1 — secure mobile seam

1. Extract and test the shared Swift Gateway client.
2. Add authenticated device enrollment and remote session transport.
3. Add an iOS 27 SwiftUI application target with Keychain-backed pairing.
4. Prove create session, send turn, stream events, cancel, approve, reconnect,
   and reject an unauthorized device.

Exit proof: an iPhone fixture submits an actionable request and shows completion
only after the Gateway emits verified terminal evidence.

### A2 — system entry points

1. Port the existing App Intents to the shared mobile client.
2. Adopt applicable iOS 27 assistant schemas and App Intents tests.
3. Add Shortcuts, Spotlight, Action button, widgets, and Live Activities.
4. Deliver APNs notifications for approval and terminal work states.

Exit proof: the same request works from the app, Siri/App Intents, and a
Shortcut, with one durable session and identical ledger outcome.

### A3 — Apple apps

Add EventKit, Contacts, MapKit/Core Location, Photos/files, then optional
HealthKit and HomeKit adapters. Each adapter needs a narrow capability grant,
preview for writes, denial tests, audit evidence, and a recovery path.

Exit proof: cross-app routines can gather permitted context and perform approved
actions without bypassing WorkLedger verification.

### A4 — iOS 27 intelligence

Add Foundation Models availability routing, structured generation, tool use,
multimodal preparation, Visual Intelligence search, and Evaluations suites.
Keep cloud or Gateway fallback for unsupported devices and complex work.

Exit proof: model-version evaluation gates pass, offline behavior degrades
cleanly, and no local-model response can falsely complete actionable work.

### A5 — daily droid experience

Add Watch controls, travel modes, proactive briefings, location-aware routines,
and reliable notification handoff. Store personal configuration, credentials,
mission data, and learned routines under the operator's Jaeger state rather
than in this repository.

Exit proof: a multi-day trial survives host restart, phone network changes,
expired credentials, denied permissions, interrupted streams, and canceled
work without losing or falsely completing a task.

## First implementation slice

Begin with A1. Do not start by adding every Apple permission. The first useful
vertical slice is:

1. shared Swift Gateway client;
2. authenticated pairing;
3. iPhone chat and one `Ask Jaeger` App Intent;
4. streamed status, approval, cancellation, and verified completion;
5. integration tests against an isolated `JAEGER_STATE_DIR`.

This proves the permanent droid is reachable and trustworthy before Calendar,
Photos, Health, Home, travel, or proactive automation increase its authority.

