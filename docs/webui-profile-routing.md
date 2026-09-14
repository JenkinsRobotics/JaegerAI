# Web UI profile routing

The Web UI on port 8790 sends `StartRunRequest.profile` to the runner on
8791. `RunnerBroker` binds each conversation to its runtime before dispatch:

| Profile | Execution owner |
| --- | --- |
| `default` (Hermes Agent), `hermes` | Authenticated Hermes native Runs API |
| `openclaw` | OpenClaw native gateway |
| `jaeger`, `jaegerai` | Jaeger bridge |
| `roundtable` | Native Roundtable service |

The runner also owns `/v1/profiles`. With
`HERMES_WEBUI_RUNNER_PROFILES=1`, the browser lists exactly Hermes Agent,
Jaeger AI, OpenClaw, and Roundtable. Incidental Hermes state directories do
not become selectable frameworks. The legacy `hermes` routing alias remains
valid for existing conversations; its files are preserved.

Readiness comes from the Jaeger bridge, authenticated Hermes native health,
and authenticated OpenClaw connection. Roundtable requires all three members.
These checks are cached for five seconds. Local Hermes folder skill counts
are omitted because they do not describe the native execution owners.
Fresh installations seed missing profile model selections without copying
credentials or chat history. Existing profile configurations are preserved.

Roundtable forwards the selected model and provider to each native member in
every phase. Member sessions remain stable across subsequent table turns.

An omitted profile retains the legacy direct-runner Jaeger contract. The Web UI
supplies its session's explicit profile. Unknown profiles fail explicitly;
there is no fallback to a different framework. Native session IDs are stable
and namespaced by framework. The native runtime retains conversation context;
the runner separately saves the full display history for Web UI writeback.

The launcher and service do not synthesize a process-global
`HERMES_WEBUI_GATEWAY_BASE_URL` that overrides profile configuration. An
explicit operator override is still respected by the Web UI.

Approval and cancellation target the accepting run. Restart recovery uses
saved native receipts without resending work. Uncertain native execution is
reported as interrupted and requires native reconciliation before retrying.
The runner persists admission before native dispatch, including Roundtable.

Conversations created by the old runner may contain Jaeger replies even when
the browser displayed Hermes or OpenClaw. These transcripts remain intact.
Start a new conversation under the intended profile instead of reusing a
conversation bound to the wrong runtime.

Hermes and OpenClaw require their native services to be running. The default
Web UI workspace maps to the native workspace. Custom workspace overrides and
attachment transfer through this new native runner path are rejected explicitly
until their transport is supported. Jaeger's existing path remains available.

## Verification

Regression tests cover routing, conversation history, model forwarding,
approval ownership, cancellation, native failure, restart recovery, and durable
Roundtable admission in `dev/tests/jaeger_ai/interfaces/test_webui_profile_runner.py`.
Existing runner/native-runtime tests cover protocol compatibility.

Live verification on 2026-09-14 used
`dev/scripts/verify_webui_profiles.py`: two turns each for all four profiles,
unique random codes, and a second prompt that omitted the code. All eight
turns completed, recalled the correct code, and saved two then four messages
through the browser-facing session API. Roundtable additionally produced
seven successful native member completions per turn; each member's independent
second-turn answer recalled the code. Browser automation was unavailable, so
visual rendering was not verified; dropdown behavior has JavaScript regression
coverage. Run the verifier with `--report /tmp/profile-verification.json` to
repeat this opt-in check; it creates new chats and does not alter existing ones.

Live synthetic two-turn chats passed through `/api/session/new`,
`/api/chat/start`, `/api/session`, and `/api/chat/stream` for Jaeger, OpenClaw,
Hermes, and the default Hermes Agent profile. Each recalled its own unique code;
each saved four messages and replayed a terminal SSE event. Run receipts prove
the accepting native runtime. Browser rendering itself was not visually tested.

After a runner restart, all four profile names completed a third turn, recalled
the same code and returned six messages. The affected suite passed 103 tests.
The service-toggle test also now mocks sibling-container discovery and cleanup;
previously its forced-start branch could stop the operator's real Hermes container.
