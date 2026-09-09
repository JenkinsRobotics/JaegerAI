# Profile-switch feature audit — September 9, 2026

Result: switching profiles routes basic conversations, but does not switch every feature to the selected agent's native implementation. This is not a feature-parity pass. No screenshots or visual automation were used. No production settings, schedules, memory or skills were modified by this audit.

## Executed checks

- Used a separate HTTP cookie jar to switch default → jaeger → openclaw → roundtable → jaeger → default. The user's browser cookie was not changed.
- Queried ten read-only endpoints on each switch: active profile, sessions, skills, memory, MCP servers/tools, commands, crons, agent health and models. All 60 requests returned HTTP 200. HTTP success alone does not establish correct runtime ownership.
- Explicit profile requests returned the corresponding active identity. Three foreign-profile conversation requests were correctly rejected with HTTP 409.
- Four labeled WebUI sessions were created for real two-turn continuity tests. Hermes and OpenClaw passed both turns and persisted replies. Jaeger and Roundtable remained pending for approximately 167 seconds and were cancelled by this audit. Jaeger's native ledger reported queued work; this is not proof of a profile-switch routing error.
- OpenClaw returned the correct README first line in a separate read-only file request, but the WebUI stream had no tool events. The answer alone does not prove tool execution.
- A structured-input request to Jaeger's active adapter returned HTTP 400: `A session_id and non-empty text input are required`. This is the envelope used by the WebUI multimodal path, so image/multimodal compatibility is not established and that path is rejected by Jaeger.
- The same format probe against OpenClaw was accepted by its legacy route; cancellation returned an HTTP error. Source explains that legacy cancellation returns 501 for an existing run because it cannot confirm termination. The probe requested only a format-validation response. Roundtable closed the structured-input request without an HTTP response. No image or private attachment was sent.

## Feature matrix

| Feature | Result | Evidence / implication |
| --- | --- | --- |
| Profile identity and session listing | Pass for tested switches | Active identities change; lists are profile-scoped. |
| Cross-profile session access | Pass for three tested pairs | Foreign session requests rejected with 409. |
| Text chat and follow-up context | Hermes/OpenClaw pass; Jaeger/Roundtable unresolved | Real distinct check words; Jaeger remained queued. |
| Skills panel | Wrong native ownership for non-Hermes agents | `_active_skills_dir()` reads `<Hermes profile>/skills`. Jaeger/OpenClaw show zero skills; this does not mean their native engines have no tools or skills. Roundtable shows 78 local Hermes-style skills, not an aggregate member inventory. |
| Memory/persona panel | Profile-isolated, but not native agent memory management | Paths point to `.hermes/profiles/<profile>/memories/{MEMORY,USER}.md` and `SOUL.md`. No native Jaeger/OpenClaw memory-edit bridge in this route. |
| Automations | Native scheduler not selected in current setup | Profiles use `webui_chat_backend: gateway`; `runtime_adapter` is unset. `_runner_schedule_forward()` only forwards when the separate runner mode is enabled; otherwise Hermes cron storage is used. |
| Model selection | Native model override omitted | Active profile adapters use `RunsHTTP.create_native_run()`, which forwards session/input/workspace, not the request model/provider. Jaeger's separate `hermes_webui_adapter/server.py` has model support, but is not the same adapter contract used by the active gateway profile. |
| Agent health | Incorrect scope/stale status | All four profiles return the same stale Hermes gateway status and `gateway_chat.enabled=false`, despite named profile configs specifying gateway mode. |
| OpenClaw tool progress/approval/cancel | Legacy path limitations | Live chat emits warning/token/done without tool events. Legacy capabilities report approval false; cancellation cannot confirm execution stopped. |
| Jaeger/Roundtable cancellation | Acceptance is not completion proof | WebUI returned `cancelled:true`; Jaeger durable run remained `cancelling`, native ledger `queued`, `execution_unknown:true`. Do not present that as confirmed native termination. |
| Multimodal attachments | Jaeger fails; Roundtable fails bounded-response check; OpenClaw unverified | Structured-input probes above; no real image transcription/vision test performed. |
| Commands | Catalogue is not native capability proof | 89 commands for Hermes/Jaeger/OpenClaw; 94 for Roundtable. Individual mutating commands were not executed. |
| MCP panel | Inventory loads; execution ownership unverified | Non-Hermes profiles expose 50 tools from profile-configured MCP inventory. This does not prove the native chat agent uses the panel's toggles. |
| Updates | Separate component updater | Hermes Agent/WebUI only, now explicitly labeled; changing chat profile does not select an update target. |
| Voice, browser shortcuts, mobile UI, uploads, destructive settings | Not verified | No visual automation, hardware testing or real settings mutations in this audit. |

## Repair order

1. Investigate queued Jaeger work and make cancellation status reflect native terminal evidence.
2. Establish a per-agent capability response that the UI uses to expose supported controls and explain unavailable ones.
3. Route native settings, model choices, memory, skills and schedules through each owning adapter. Do not relabel Hermes profile files as native state.
4. Wire and test OpenClaw native tool/approval/cancellation support, including the deployed launch configuration.
5. Implement supported multimodal inputs or reject them clearly before submission; Roundtable must return a structured error instead of dropping the connection.

Raw sanitized read-only endpoint summaries are in `profile-switch-evidence-2026-09-09/read-only-endpoints.json`. Transient live logs: `/tmp/jaeger-profile-audit-live.log`, `/tmp/jaeger-profile-openclaw-tool.log`. Test sessions: Hermes `7665c927fe6e`, Jaeger `535e06a3b044`, OpenClaw `084dbcd91e95`, Roundtable `7286321dcf4c`; OpenClaw file probe `b8554189c5fe`. They remain labeled for inspection. No blanket service restart was performed.
