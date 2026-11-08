# Combined assistant-core qualification, 2026-11-08

## Seventeenth increment: PARTIAL

Production source is 35100a1e477a5eaebc21cd4fc66f3f25b530f015. This increment
adds test-only request/session/PID-scoped fault hooks and actual owned-child
SIGKILL qualification, plus reports. No production implementation is changed.

- Repository verification: 430 passed.
- Production-path: 75 passed.
- Security: 203 passed, 2 platform skips.
- Durable/recovery: 491 passed.
- Agent runtime/commitment: 120 passed.
- Separate unshimmed specialist OWNER integration: 1 passed.
- Owned HTTP/process: 49 passed, 1 failed, 3 infrastructure exclusions.
- All four strengthened process-loss cases passed, including both-restart
  status, file bytes/mtime, model/tool/effect, projection and queue assertions.
- Root and agent archives rebuilt without installation; six unchanged
  companions retained, all ten inspected. Nine root and five agent runtime
  modules match source exactly, with the verified no-mock UI fingerprint.
- Critical Python lint, source freeze and whitespace checks passed.

Counts overlap. UI source is unchanged from the 910-test/201-file build; all
866 source files and the 857-input fingerprint matched independently. That
prior UI result is reused, not a fresh rendered-browser run.

## Blocking combined regression

The existing test_new_chat_default_snapshot_survives_real_retry fails because
the original implicit unpinned first turn correctly has no lead marker, but its
retry incorrectly mints _owner_agent from the now-current route. This changes
immutable execution identity. The exact execution-equality assertion remains
unchanged. Producer repair and renewed combined qualification are required.
The failing result and source are retained, not relabeled a pass.

The four process-loss tests themselves pass on this combined source. They use
real authenticated proxy admission, native tools, approval, ledger, verified
TaskCard and SQLite proof; only provider replies and fault barrier are scripted.
They qualify explicit pinned lead recovery, not every possible resident path.

## Reproduction and limits

The cumulative evidence contains run-seventeenth-final.sh, per-gate logs and
seventeenth-source-freeze.sha256. Always use a fresh external basetemp, since
pytest clears that directory. The HTTP fixture deliberately disables optional
skill smoke subprocesses; production defaults are unchanged.

Overall and every tab remain PARTIAL. Actual browser/phone/native-host,
configured providers/accounts, voice/media and native-bridge restart are not
qualified. Historical markerless identity and unsupported/background/attachment
paths remain conservative. Registry/SQLite validation is not one cross-store
transaction. Same-tab drafts and bounded foreground continuation retain their
previous limitations. The headless environment does not pass every package
suite. Archive inspection is not proof of installed behavior.

No Mac runtime mutation, merge or deployment occurred. Dirty runtime work and
operator data remain preserved. GitHub write is blocked; no remote branch,
PR or CI exists. See the per-tab and increment reports for detailed boundaries.
