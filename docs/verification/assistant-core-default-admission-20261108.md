# Default Chat execution snapshots, 2026-11-08

Eighth isolated increment after `52453916584b360871ed861197e2492e0c9715af`.
All preceding commits are preserved. No runtime-Mac edits, installation, restart,
merge, deployment or further denied GitHub write attempts.

## Confirmed ordinary new-chat gap

The UI creates a normal session without model, provider or workspace metadata,
then sends text, request ID and attachment IDs. Previously admission preserved
`model=None`, `provider=None` and an empty workspace, although runtime execution
resolved actual instance defaults later. The sixth increment correctly refused
to infer continuation authority from those later mutable defaults. Consequently
the common new-chat path could not use that scoped continuation.

An external handler/store regression produced one failure and seven passing
precedence/replay/tool-grant controls. This increment freezes supported effective
defaults in the original immutable execution snapshot, before any dispatch.

## Bounded repair and authority

- A lazy server-owned resolver runs only for fresh admission, after existing
  receipt replay, busy and revision checks. Defaults are separate from the client
  request fingerprint and do not silently change session metadata or tool grants.
- Resolution reads the resident owner's layout and configuration. It does not
  construct a model client, read credential values, discover models, contact a
  provider or initialize an Entity to discover defaults.
- The server-owned `_instance_defaults` marker retains the effective absolute
  workspace and a hash of non-secret route selectors. It is not accepted as a
  client execution field, raw task instruction or mutable legacy session setting.
- Pinned instance defaults retain instance mode, including bare-file destinations
  and workspace/skills write roots. They are not promoted into an explicit
  project. Explicit workspace/project choices retain their existing behavior.
- Runtime rejects incompatible default route or workspace drift before model or
  tool dispatch. The hash covers enabled/model/provider/base URL and credential
  selector names, not credential values, secret rotation, sampling, context size
  or timeout tuning.
- Retry and internal tasks use a shared canonical-source proof. Admission rereads
  the source request in its transaction and verifies source session and immutable
  authority; Retry also binds its expected original snapshot. Missing, forged,
  stale or cross-session sources and caller/tool widening reject or pause.
  Explicit compatible narrowing is retained; incompatible explicit route/project
  changes drop only their old default-marker component.
- The two existing specialist handoff adapters prove the current canonical mode
  before omitting an inherited instance-default workspace. Explicit project choice
  wins. They continue not forwarding parent model/provider or internal marker
  authority, preserving the specialist's routing behavior.

## Review corrections and limitations

The initial naive workspace-to-project snapshot failed two owned HTTP cases while
two explicit/session-default controls passed. Read-only path probes confirmed it
would redirect new bare files from skills into workspace and change write roots.
The retained instance mode repairs that behavior instead of claiming equivalence
from tests that only use workspace-prefixed paths.

Independent review also caught default-marker loss on Retry and model-submitted
background tasks, a raw task marker-injection ingress, historical mutable-metadata
and arbitrary task-payload trust, and implicit workspace promotion by handoff
adapters. Canonical source proof and the bounded adapter changes address those
paths. An independent route check of registered, alias-like and tagged model names
found no separate `select_client` mismatch for the supported exact routes.

Support remains conservative: qualified external providers must have identity
normalization in the existing routing table. Provider aliases such as
`ollama-cloud`, ambiguous provider-only choices, CLI/local defaults and unresolved
routes are not newly expanded. No configured real provider was exercised.
Normal production startup initializes the owner before serving first Chat; if
startup fails or is bypassed, admission does not boot it and leaves defaults
unresolved. Historical digest-version-one receipts cannot establish new marker
inheritance. Existing attachment and foreground-transfer restrictions remain.

## Qualification

The isolated pre-integration candidate passed 177 application tests, six owned
HTTP/native scenarios, 29 package tests and repository verification. Independent
review passed 129 focused admission, authority, Retry, adapter and package checks.
Both changed `jaeger-agent` modules matched a separately rebuilt wheel. These
results are candidate evidence, not substitutes for merged-source qualification.

The overlapping owner hunk was reconciled explicitly, preserving the seventh
increment's request-collision handling. The new immediate/queued session-binding
checks, generic conflicts, newer-attempt guard and no-foreign-cancellation behavior
remain intact. Main-source focused tests passed 274, package tests 29, and seven
owned HTTP scenarios. Independent merged review passed 135 checks plus six targeted
race/narrowing/revocation/foreign-session controls.

The first broader production gate caught a compatibility regression: 74 passed
and the existing voice real-Gateway contract failed because the scripted Entity
has no layout. The producer had unconditionally dereferenced layout even for
markerless selections that do not need it. Five new boundary controls reproduced
that failure. Passing optional layout to the existing resolver repairs the old
contract without creating a fallback workspace: a frozen workspace still rejects
missing layout before callbacks, models or tools. No voice fixture was widened.
The corrected default/voice target passed 61, and the full production gate passed
75. The failed log and previous source manifest are retained.

Final qualification against the frozen merged source:

- Repository `scripts/verify.sh`: **PASS, 430** across its existing tiers.
- Production-path: **PASS, 75**, 18.51 seconds after the compatibility correction.
- Security: **PASS, 203**, with two platform skips, 19.56 seconds.
- Expanded durable/recovery aggregate: **PASS, 262**, 129.25 seconds.
- Full selected owned HTTP/process suite: **PASS, 41**, 466.51 seconds, with
  three existing browser/attached-client infrastructure exclusions.
- Independent final default-admission suite: **PASS, 51**. The review report
  records exact commands and marks reconstructed tool-output evidence as such.
- Changed Python critical lint and `git diff --check`: **PASS**. The first lint
  attempt could not write its default external cache; `--no-cache` with the
  isolated HOME passed. No source/cache permission was changed.
- Root and agent wheels/sdists rebuilt without installation. All ten archives
  inspected, retaining six unchanged companion archives. All six changed root
  runtime modules and both changed agent runtime modules match final source.
- The unchanged no-mock UI build has fingerprint
  `f6e4f00489d65292d6c25d21deafe2a77332c8708939c23f288e1bf8bfbd139c`.
  Its earlier 879 tests in 200 files are retained, not represented as a new run.

The twelve-file runtime/test manifest has SHA-256
`a34e2c63f53be27faf9dd8958de1d0ff0471e81b4aa1d36f4d6affefebfcc6d9`.
Every hash was rechecked after aggregate tests. Counts overlap and qualify only
the stated boundaries; these are not live-provider or full-product acceptance.

The review bundle includes `run-eighth-final.sh` with exact isolated environment,
state/cache/PYTHONPATH, expanded durable targets and archive commands. Its gates
are `verify`, `production`, `security`, `durable`, `http`, and `packages`. The HTTP
gate runs the committed owned-process, document-journey and request-identity
modules with `--timeout=120 -k 'not owned_browser and not attached_client'`.
Use disposable external HOME/state/cache and Python 3.12; never runtime data.
The prior test-environment report lists this headless environment's dependencies.

The HTTP profile inherits the seventh report's explicit fixture boundary:
provider transport is scripted, optional skill smoke subprocesses are disabled,
and non-core missing-smoke gating/cold production initialization are not qualified.
Real native execution, tools, approvals, ledgers, checkpoints and receipts remain
in scope. The production smoke default is unchanged.

## Remaining acceptance

A separate Queue next audit reproduced three failures with six passing controls:
its enqueue path does not receive these defaults, so promotion can retain an
incomplete snapshot. The eighth increment does not silently backfill queued
records. That bounded follow-up remains outside this increment.

Overall product and every tab remain **PARTIAL**. Browser/phone/native-host,
real provider/account and live deployment acceptance remain unqualified. No
default-branch merge, PR or deployment is represented by a local patch. Existing
runtime-local work and all user data remain untouched; reconciliation, backups,
complete acceptance and separate cutover approval remain required.

## Later queued admission repair

The [ninth increment](assistant-core-queue-defaults-20261108.md) extends the same
fresh-default producer to Queue next, with actual queue/native and bare-path
evidence. It does not backfill historical receipts or expand supported routes.
