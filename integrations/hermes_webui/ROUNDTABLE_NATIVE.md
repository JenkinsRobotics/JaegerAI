# Native Roundtable — staged backend contract

September 6, 2026. This backend is opt-in, not the currently deployed WebUI
group-chat experience. Do not enable `ROUNDTABLE_NATIVE_RUNS` in production until
the UI gateway, approval/control recovery, bounded storage and release gates in
`RELEASE_PROGRESS.md` pass. The existing Markdown path remains the default.

## Ownership and continuity

`roundtable_native.TableService` coordinates the actual Jaeger bridge, Hermes
native API and OpenClaw gateway. Each table/member pair retains its existing
native session identity. Hermes also retains the legacy named-session lookup.
The table stores decisions, task assignments, evidence and attempt identities;
it does not reconstruct native history by nesting old transcripts in new prompts.

Private SQLite ledgers and member Runs receipts live below
`.jaeger_ai/shared/roundtable`. Dispatch intent and session ownership are recorded
before native work. Failed observers are not replayed. Unknown native outcomes
retain their session locks until terminal evidence permits reconciliation.
Only Jaeger currently has the native receipt query needed for automated recovery;
Hermes/OpenClaw control recovery after observer restart remains incomplete.

## Selection and modes

The Runs capability response contains one canonical registry of
modes, mentions and chair policies. A create request accepts a `roundtable` object:

```json
{
  "session_id": "existing-table-id",
  "input": "Review this proposed change",
  "roundtable": {
    "mode": "review",
    "members": ["jaeger", "hermes", "openclaw"],
    "muted": [],
    "chair": "rotate"
  }
}
```

The same modes accept `/ask`, `/collaborate`, `/quick`, `/vote`, `/review`, and
`/incident` prefixes followed by a question/task. `@Jaeger`, `@Hermes`,
`@OpenClaw` and `@all` narrow participation within configured, unmuted members.
Explicit UI choices are persisted per table; slash modes override that turn.
Without an explicit mode, plain questions default to ask, with simple intent
selection for reviews, incidents, votes and collaboration requests.

| Mode | Enforced workflow |
| --- | --- |
| ask | Parallel independent answers, one parallel discussion, recorded ballots, chair summary |
| collaborate | Volunteers, unique task owners, parallel contributions, discussion and summary |
| quick | One eligible member; no forced discussion or chair |
| vote | Independent proposals, explicit ballots, recorded result and summary |
| review | One proposer, followed by selected members' critiques/ballots and summary |
| incident | Separate diagnostics, evidence gathering and remediation-proposal responsibilities |

Rotating chairs advance past the previous chair persisted for the table, even
after service restart. Least-involved limits selection to eligible members with
the fewest current-turn contributions. An unavailable explicitly chosen chair
is not silently replaced.

Workspace overrides currently fail explicitly. The gateway must not send its
default `/workspace` value unless native workspace negotiation is implemented.
Native model/host/thinking overrides are also not implemented in this contract.

## Live messages, evidence and controls

Every child attempt has its own stable message ID, native session and run ID.
Events include `member.message.delta`, `member.message.replaced`, native states,
tool events, member completion/failure/stall, assignments, proposals, decision,
chair selection, ledger and summary. Parent event IDs cannot be replaced by a
child payload. Approval requests retain their own opaque IDs and member owner.

Authenticated routes include:

- `POST /v1/runs`, plus the existing run snapshot/events/Stop/approval/reconcile routes.
- `GET /v1/runs/<table-run>/ledger`.
- `POST /v1/runs/<table-run>/members/<child-run>/stop`.
- `POST /v1/runs/<table-run>/members/<child-run>/retry`.

Retry requires a known failed/cancelled native outcome, retains that member's
session and original bounded prompt, and does not rerun other members. The table
must no longer own active work before accepting the retry. Stop is intent until
the native runtime confirms termination; it never becomes an outage diagnosis.

Member prose is reported, not verified. A native `tool.completed` event creates
an attributed, timestamped tool-execution receipt; it does not verify arbitrary
claims in the answer. Assignment completion is `response_received`, not a false
assertion that real-world work is finished. Native tool permissions still govern
execution. Prompt-based task boundaries are not per-turn capability sandboxes.

Only a single explicit `roundtable` JSON block supplies a ballot. Invalid,
duplicate, missing and failed votes cannot count as agreement. The denominator
retains every selected member. Unanimity requires all selected votes to support
a proposal; a majority is strictly greater than half. Dissent, abstentions,
truncated proposals and unresolved decisions remain visible in the ledger.
An LLM chair's prose is commentary, not authority to override recorded votes.

## Progress and remaining limits

The new orchestrator has separate configurable queue, idle, tool and approval
budgets; its total budget is optional and disabled by default. Native meaningful
progress advances the appropriate clock; transport heartbeats alone do not.
An explicit total budget spans phases rather than resetting for each phase.
Upstream connect/read/provider timeouts remain separate and require further
verification. The live legacy path still has its old phase limit.

This implementation does not yet provide bounded event journals/retention,
durable browser route pins, restored approval controls, a group-chat renderer or
selectors. `message.replaced` must be handled by the gateway and renderer before
deployment. Do not advertise the complete feature list as shipped.

## Verification

`test_roundtable_native.py` covers real HTTP framing/auth and isolated native
backend substitutes, including parallel partials, modes, explicit ballots,
ownership, isolated failure/retry, native session continuity, tool attribution,
progress budgets, chair rotation and unknown-outcome reconciliation.

Run the opt-in live test separately from the root test suite:

```sh
.venv/bin/python scripts/verify-roundtable-native.py
```

It uses provider tokens and creates labelled verification conversations. It
denies unexpected approvals, requests no tools or file/memory writes, proves
partials arrive while native workers are active, and checks second-turn recall
without reinserting the check word into the orchestration prompt. This verifies
the native backend, not browser presentation or complete tool/control parity.
