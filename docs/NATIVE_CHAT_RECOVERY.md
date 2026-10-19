# Native chat recovery and conversation switching

Source candidate only. No app installation, live session creation, live turn, service restart or deployment was performed. The separate Stop-only release candidate remains unchanged. Speech worker files `Voice/TTS/TTSManager.swift` and `core/ui_speech.py` were not edited.

## Demonstrated defects addressed

History load previously restored only completed turns through the bridge; it never attached to Gateway SSE. A recovered running conversation could therefore expose Stop but never show its continuing answer. Bridge deltas also carried no session identity at this UI boundary: they were applied to whichever conversation happened to be visible. Delayed history reads and delayed local reply/identity lookups could overwrite a later selection, with an array index held across an await. New Chat minted only a local key, so it did not create a durable empty conversation.

## Frontend behavior

- History selection uses an authenticated Gateway snapshot, then attaches to that conversation's existing SSE stream. The snapshot includes persisted messages, active/latest request identity, partial answer and replay cursor.
- Recovered text streams only into the matching session and request. Events at/below the cursor and deltas from another request are ignored. New external turns and terminal events reread authoritative state.
- Stream failure or closure displays reconnecting and retries reads after two seconds. Reconnect takes a fresh consistent snapshot before reopening the stream, including when an old cursor expired. No turn, cancellation or queue operation is submitted by this observer.
- Cancelled/unknown settlement remains truthful and pauses retained client messages. Partial text survives. Queued text is retained and shown after snapshot refresh, and observation never drains the queue.
- New Chat and History remain available during a turn; navigating does not cancel execution. New Chat creates a durable empty Gateway session using one stable client-generated ID; it does not cancel the previous session. Creation failure/uncertainty is explicit and is not automatically retried.
- A selection generation makes the latest New/Switch intent authoritative. Late reads, replies and identity lookups cannot overwrite a newer conversation. A failed switch keeps the current transcript, shows the failure and restores its observer. Scoped Stop still captures its displayed request before waiting.
- Local bridge deltas are accepted only while the matching locally submitted session is selected. While that single bridge turn is pending, text entered elsewhere is retained and paused; it cannot launch automatically when the background reply returns. Existing in-flight work is not cancelled merely to navigate.
- An authoritative 404 can fall back to existing local-only history using `resume: false`; this is explicitly labelled as history without a Gateway live attachment. It does not execute a legacy resume.
- Existing rendered activity/identity is retained when canonical message text agrees. Local sends still use the existing bridge admission path, request identity and approval semantics.

## Connection and backend changes

- Added typed Gateway conversation snapshot and an injectable read/create/stream client contract. Existing Gateway auth and session confinement remain in force. New Chat calls the already-supported session creation API; it does not invent another session store.
- `GET /v1/sessions/{id}?view=conversation` returns the conversation projection. SQLite reads messages, latest nonqueued receipt, partial text and event cursor in one read transaction, so a concurrent writer cannot create a gap between history and subsequent events.
- Partial text comes from the existing durable activity history for the latest request, including after SSE replay retention, and is omitted when a final assistant answer is already persisted. No database schema or execution lifecycle was added. Existing control projection and normal session reads are preserved.
- The native Open Web Chat action also resolves the selected instance and reports discovery failure instead of falling back to a fixed port.
- Separate reviewer repair `a5ba4413`: parse exactly one validated standalone browser address from `jaeger webui url` output; ignore labelled remote/diagnostic lines; reject invalid, credential-bearing or ambiguous addresses. Host/profile/auth handling is unchanged.

## Focused verification

Four Swift recovery fixtures cover delayed selection, duplicate/wrong-request deltas and New Chat detachment, external cancel with retained queue/partial text, and disconnect/reconnect rebasing. The ten reviewed Stop control/race/queue checks are included to protect the modified send and queue paths. Two endpoint parsing checks cover multiline/noisy/invalid/ambiguous output. Four isolated SQLite checks cover partial/request/cursor consistency, terminal deduplication, unknown preservation after replay retention and a concurrent WAL writer between history/cursor reads. External scratch and caches only; no broad monorepo sweep or model call.

## Remaining limits

Recovered attachment currently rebuilds text and request status, not historical reasoning/tool/approval cards, attachments, structured message parts or context-usage accounting. Existing canonical activity is not deleted; those richer native projections remain separate work. A pending approval may be visible as request status without its actionable card in the recovered view; approval authority and existing presenters are unchanged. Recovered turns are not automatically spoken.

Legacy local-only histories have no Gateway live cursor until a Gateway session exists. Native sends still share one bridge in-flight continuation; this change retains/pauses messages in another selected conversation rather than introducing concurrent execution. SSE retry uses a fixed two-second read-only interval. Installed-app, live-provider and cross-client acceptance remain unverified. These source changes require re-review and an explicitly approved backend/native rollout; they are not installed fixes.
