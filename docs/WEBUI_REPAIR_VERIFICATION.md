# WebUI repair verification record

Date: 2026-09-15
Branch: `codex/webui-integration-continuity`
Worktree: `/private/tmp/jaeger-webui-integration`

## Production evidence collected before editing

- Affected session: three `POST /api/chat/start` requests returned 200, but the PWA client
  sent no matching `GET /api/chat/stream` until the page was reloaded.
- All three corresponding native runs reached a confirmed terminal result with
  `execution_unknown=false`; their replies were already persisted when refresh displayed them.
- A disposable client attached to `/api/chat/stream` and received token frames, `done`, and
  `stream_end`. This isolated the failure to browser stream attachment rather than model or
  server-side SSE execution.
- Live 8790 settings reported `exp-v0.52.264-15-g0c79c12b-dirty-20fcd707`; container 8787
  reported `unknown`. Gateway 8810 and Hermes Runs 8645 both returned 404 for `/version`.

## Automated results

```text
$ pytest [framework/native/profile/roundtable focused suite]
131 passed in 9.23s

$ pytest [gateway/packaging/continuity/native-adapter focused suite]
67 passed in 6.40s

$ dev/scripts/run_tests.sh  # application phase
4356 passed, 1 skipped, 87 deselected in 148.58s

$ pytest packages/jaeger-agent/tests  # Homebrew Git + isolated PYTHONPATH
908 passed in 25.09s

$ dev/scripts/run_tests.sh  # jaeger-os package phase
283 passed in 22.06s

$ node --check jaeger_ai/assets/jaeger_stream_continuity.js
[exit 0]

$ node --check jaeger_ai/assets/jaeger_webui_branding.js
[exit 0]

$ git diff --check
[exit 0]
```

The first package-run attempt exposed two host/test-runner defects: Apple Git was blocked by
the unaccepted Xcode license, and the editable install resolved package files from the original
checkout. The test runner now prefers `/opt/homebrew/bin/git` when available and puts its own
worktree on `PYTHONPATH`. The corrected package run produced the result above.

## Real Hermes Runs contract

A disposable two-turn session was sent through the running 8645 Runs API:

```json
{
  "outputs": ["STORED", "LIVE_CONTRACT_793a5fd2"],
  "memory_ok": true,
  "cleanup": 200
}
```

The second turn recovered the exact token from the first. The native session was deleted after
the check. No daemon or container was restarted.

## Disk and scope assertions

- Fresh `scripts/prepare-hermes-webui.py`: exit 0; every required patch applied.
- Staged `_version.py`: `exp-v0.52.264-15-g0c79c12b`, never `unknown`.
- Staged continuity extension and Dispatcher supervisor: present.
- In-repository `__pycache__` and `.pytest_cache` directories after verification: 0 in both
  the isolated worktree and original checkout.
- Changed branch paths under `jaeger_ai/features/finance/`: 0.
- Live services restarted or replaced: 0.
