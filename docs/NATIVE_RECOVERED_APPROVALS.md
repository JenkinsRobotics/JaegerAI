# Recovered native approval cards

Source-only follow-up to `75e348bc`. No live approval, tool, turn, installation, service restart or deployment was performed. The separate Stop candidate and speech-worker files remain untouched.

## Frontend and connection behavior

- Loading a Gateway conversation reads existing pending permissions for the exact selected session and current request. Cards from other sessions/requests are discarded. No tool or turn is replayed to generate a card.
- The card shows the stored prompt, kind, tool, target, summary/reason and task/handoff identity when supplied. It displays session, request and profile. Decision buttons come only from the stored options and supported permission choices; no default standing grant is added.
- The conversation snapshot includes up to eight existing tool/handoff status events for this request. Only event/name/status/phase/text and child/task IDs are projected; arguments and payload contents are omitted. Missing child history is not fabricated.
- Before a click is submitted, the card is reread. A changed selection, prompt, identity, options or resolved/expired status prevents submission. A selection change during preflight never retargets the action.
- Only one decision is in flight. An uncertain POST is never resent; status refresh remains available. A recorded decision is labelled as permission recorded, not proof of tool completion.
- Approval request/resolution events refresh the cards. Terminal Stop/unknown settlement removes actionable cards through the recovered request state. Local-only history and Dispatcher selection clear recovered Gateway cards; their existing paths remain separate.

## Backend changes and access boundaries

- Existing pending-approval GET accepts optional session/request filters. Existing detail GET supplies authoritative status and options; no new read authority is granted.
- Added `POST /v1/approvals/{id}/decision`, using the existing resolver and explicitly classified under the same `approve` scope. This scoped path requires expected session/request/profile. Older backends return unsupported rather than silently ignoring new preconditions.
- In the existing SQLite first-writer transaction, the optional native preconditions check approval identity, actual session profile, request membership, active request state (not cancelling/terminal) and the stored offered choice before recording a decision. Missing/stale context fails closed. Existing internal expiry/cancellation and ordinary API callers retain their contract.
- Fixed the stale resolver path: an expired/already-resolved row no longer pops or releases an in-memory waiter. It returns a stale/not-found result. A successful record still releases the existing waiter and follows existing runtime/permission behavior; no new execution path, grant store or broad proxy was introduced.

## Verification and remaining boundaries

Four focused Swift fixtures cover foreign-card filtering/offered options, expired cards, uncertain-result no-resend and selection changes during preflight. Existing four chat recovery fixtures and ten reviewed Stop checks also pass (18 focused Swift checks total). Four isolated permission checks cover session/request/profile/options confinement, stopped/expired requests, an expired API row with a live waiter and the guarded route's required context/approve scope. Five snapshot fixtures include minimal context filtering and argument exclusion. No live effect is used as validation.

Expiry follows the existing backend's stored status/timeout lifecycle; no client deadline is invented where the record has none. Unknown custom choice types are not rendered as invented decisions. This slice handles permissions bound to the selected Gateway request; it does not guess ownership of unrelated child-session or legacy approvals. Rich historical tool/reasoning cards, attachments, voice/avatar, scheduler writes and board execution remain outside this follow-up. Source re-review and coordinated deployment approval are pending.

Evidence logs: `/tmp/jaeger-recovered-approval-tests.log` and `/tmp/jaeger-recovered-approval-python.log`.
