# ide-client

Job: Jaeger in your IDE, where you do most of your work. A thin client, not a second brain.

This module does NOT copy the IDE code. The code already lives in this repo, at jaeger_ai/interfaces/ide/, and copying it here would create a second, drifting copy. This folder is the stack registration for that interface: what it is, how to install it, how it bolts on, and what to test.

Source in this repo (current, verified 2026-10-22):
- jaeger_ai/interfaces/ide/extension.js (75,865 bytes)
- jaeger_ai/interfaces/ide/conversation.js (39,451 bytes)
- jaeger_ai/interfaces/ide/gateway.js (12,276 bytes)
- jaeger_ai/interfaces/ide/commands.js (10,295 bytes)
- jaeger_ai/interfaces/ide/native-turn.js, package.json, package_extension.py, media/, tests/, README.md, VERIFICATION.md

What it does: a small, local VS Code-compatible sidebar over the existing Jaeger Gateway. Chat, streaming Markdown, approve/deny, request cancellation, queue next (Gateway-owned follow-up), /plan (plan-only, no file/shell/browser tools), /workers (Gateway orchestration catalog), context chips (active file, selection, open files, problem count), /diagnostics, session tabs, /archive, /workspace, @ file mention, /worktree (select an existing git worktree only, does not create/merge/prune).

How it bolts on:
- Build: PYTHONDONTWRITEBYTECODE=1 python3 jaeger_ai/interfaces/ide/package_extension.py --output-root /tmp/jaeger-ide-build
- Install the printed VSIX with Extensions: Install from VSIX. No Marketplace account required, no npm runtime dependencies.
- Open "Jaeger: Open Conversation", move its view to the Secondary Sidebar.
- It talks to the loopback Gateway (default from jaeger_ai/contract/ports.py, Gateway :33418). If the loopback Gateway is unavailable, it starts the managed headless runtime with `jaeger stack up` (Gateway, bridge, native MCP) without needing JaegerAI.app.
- It does NOT own sessions, memory, or execution. Histories are fetched from the Gateway owner, not copied into a new transcript database.

Limits, stated in its own README:
- Requires VS Code 1.96+ or a compatible host. Antigravity compatibility must be verified in the installed host; do not assume all VS Code APIs are available there.
- Rejects non-loopback URLs. Remote access requires a separate authenticated deployment, NOT exposing the unauthenticated Gateway. So: IDE on this Mac works; IDE from another machine over Tailscale is NOT this module's path — that is ui-remote-access (WebUI + remote_access + Tailscale Serve).
- Do NOT confuse this with features/ide_orchestration/, which launches one-shot CLI delegates, not existing IDE-panel conversations. That feature is not finished, and is not this module.

Do NOT add a second IDE extension from the Desktop archives (JaegerAI_IDE_Archive, Jaeger-UI-Archive ide-extension/). Those are the same lineage, older and smaller. One IDE client only.

Test to run when code-run is available: build the VSIX, install it, open a conversation, send a turn, approve/deny a tool action, queue a follow-up, run /plan, check context chips match the active file/selection, check a non-loopback URL is rejected.
