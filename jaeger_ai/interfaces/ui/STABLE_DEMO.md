# Minimal live Chat + Tasks demonstration

Owner direction on 2026-11-06 replaces the paused visual revamp: demonstrate real
chat, durable task records, and repeatable builds first. The default screen uses
the existing ChatPane/WebHost and TasksWorkspace/TasksBoard. Existing screens and
all their source remain available at `/?full=1` (preview, not release sign-off).
No Gateway/auth/policy/config changes, new service, daemon, port or mock data.

## Build

Tested with Node v22.23.2, npm 10.9.8 and the existing package-lock.json
(SHA256 2721b1e7f67a3020f1bea999b03340ba2fcb3178d0936f024da35).
Use the locked dependency installation in this checkout; no package upgrades were made.

```
npm test
npm run build
node scripts/stable-demo-smoke.mjs
```

The current :8790 process serves this checkout's dist directly. Verify the live
entry asset bytes against dist after building; do not assume another installation
has the same path. No daemon restart or external cache copying is required here.
A fresh lockfile installation/wheel release is not certified by these checks.

## Use

Open http://127.0.0.1:8790/ and Start conversation. This creates an independent
Jaeger session, not the stuck Builder context. The browser remembers its session
ID; history is read from Gateway after reload. Chat stays mounted across Tasks.
Task proposals use the existing runner: New task, select Jaeger as the origin,
write the deliverable, Create proposal, inspect it, then approve that exact version.
Tool actions may additionally need explicit approval: the header approval badge
opens existing Approve/Deny cards. No policy controls are bypassed.

For a verifiable local smoke task, request one text artifact in the task workspace
containing sum(1..100)=5050 and its formula, then a work_ledger paths_exist check
and complete_task. Approve only that exact local file write if prompted. The task
should reach completed_verified with a stored file_sha256 receipt.

Optional read-only smoke against known diagnostic records:
`JAEGER_DEMO_SESSION=<session-id> JAEGER_DEMO_TASK=<task-id> node scripts/stable-demo-smoke.mjs`
No diagnostic IDs are needed for ordinary use. The smoke script never sends or approves.

## Evidence and limits

Live chat returned PONG and a later browser-sent reply streamed incremental text,
then persisted across task tab switches and page reload. A diagnostic task went
paused → queued → running → completed_verified with a 50-byte file and SHA256
9a5d141b0f05423c82463c58f29f6654bbafae7ec3c5fc67b3a52410be67b087.
Another isolated task was explicitly cancelled during execution; its terminal
receipt confirmed cancellation. The old stuck Builder request was untouched.

A file-forbidden arithmetic-only task exposed the runner's objective-verification
requirement; arithmetic output alone did not falsely count as completed_verified.
No production worker was killed. Crash/reboot recovery and automatic retry after
worker interruption are NOT demonstrated. Task survival across UI disconnect/reload
is demonstrated, not an always-on execution guarantee. The underlying runtime/source
drift audit remains separate and was not used to justify installing anything.
