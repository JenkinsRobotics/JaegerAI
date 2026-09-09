# Phase 1 adapter changes — September 9, 2026

## Implemented and tested

- `RunsHTTP.create_native_run` preserves model/provider selection. `BridgeClient.turn` carries it through to Jaeger's turn worker.
- Jaeger supports conversation-scoped external-model selection. It creates the selected external client, carries session messages when rebuilding the agent, keeps other sessions on their own clients, stamps the actual selected model in session history, and does not write instance configuration. Changing local in-process or CLI models remains an explicit instance setting; unsupported per-conversation selections fail rather than silently using another model.
- Structured user-message envelopes and text blocks are accepted. Image/file URL or path references are retained. Valid supported base64 attachments become private 0600 files under the run receipt directory; the native agent receives their paths for file/vision tools. Unknown blocks, malformed data, unsupported schemes and empty input produce explicit validation errors. This is attachment access through native tools, not direct multimodal content injection into every model provider. Native tool/model availability still determines whether an image can be understood.
- Queued Jaeger bridge requests can be withdrawn immediately, under the same lock used by the worker to acquire them. The bridge writes a durable cancelled receipt, sends a terminal reply and leaves a tombstone the worker skips before slash/tool/model execution. Active work cannot be falsely withdrawn using this path.
- Native cancellation responses now include actual run status, confirmation and execution uncertainty. `native-cancel-status.patch` makes the WebUI require confirmed terminal cancellation for that contract, instead of treating HTTP acceptance as proof of stopped execution.

## Verification

- Full Python suite: 3,819 passed, 1 skipped, 1 existing Discord audioop deprecation warning (116.88 seconds).
- Focused suite after final cancellation-response changes: 46 passed.
- Conversation isolation/history test: passed alongside client/config isolation test.
- Three assembled-WebUI cancellation cases: pending is not confirmed, terminal/known cancellation is confirmed, terminal/unknown execution is not confirmed.
- Changed Python modules and assembled gateway module compile; static fatal-error checks and git diff whitespace check pass.
- Upstream-plus-overlay assembly succeeds; vendor submodule remains unchanged.

## Deployment boundary and remaining work

The host services were restarted after the operator instructed continued completion. Jaeger’s real WebUI two-turn check passed after deployment. Native OpenClaw chat and confirmed cancellation passed; native Roundtable completed two multi-member turns with streamed member events and retained context. Installed OpenClaw/Roundtable launch agents now enable those native transports. The WebUI cancellation and capability patches are installed in the running container, and the overlay builder reproduces them without changes in the vendor submodule.

OpenClaw per-session model changes require `operator.admin`. The existing paired device lacks that scope; a request for expansion was rejected by OpenClaw and operator approval remains pending. Selecting its already-effective model succeeds without escalating permissions. Roundtable advertises that a single-model and workspace override are unsupported; the gateway omits those automatic WebUI fields. Structured Roundtable input is normalized before planning, and host attachments include published container mount references.

See [Dispatcher implementation and verification](DISPATCHER_FOCUS_2026_09_09.md) for subsequent native routing, memory/skills panels, live attachment/model evidence, and the remaining WebUI login/extension-consent boundary.

The suggested fix of unconditionally marking active work cancelled was deliberately not implemented: it would permit overlap while execution is still active or uncertain. The original `session_busy` guard was not itself proven to cause the observed pending turn. The new queue withdrawal fixes the demonstrated inability to settle a queued cancellation without waiting for the worker.
