# Jaeger IDE client

A small, local VS Code-compatible sidebar over the existing Jaeger Gateway.
No donor agent runtime, new database, paid SDK, or Marketplace publication.
The UI selectively adapts Kilo Code's MIT-licensed frame queue and stable-key
transcript mechanisms; exact provenance is in `THIRD_PARTY_NOTICES.md`.

## Build and local installation

Requires Python 3, Node 22+, npm, and VS Code 1.96+ (or a compatible host).
The packager downloads pinned Microsoft VSCE tooling into an external cache;
the extension itself has no npm runtime dependencies or build step.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 jaeger_ai/interfaces/ide/package_extension.py \
  --output-root /tmp/jaeger-ide-build
```

Install the printed VSIX with **Extensions: Install from VSIX…**. No Marketplace
account is required. Open **Jaeger: Open Conversation**; move its view to the
Secondary Sidebar using the host's Move View controls for the right-hand column.
Antigravity compatibility must be verified in the installed host; don't assume
all VS Code APIs or other agents' private APIs are available there.

`--stage-only` produces an external extension directory for an isolated extension
development host. Do not run npm install, package caches or build outputs here.
Canonical default Gateway port is generated from `jaeger_ai/contract/ports.py`.

The Gateway must already be running (`jaeger gateway daemon`). The extension
does not launch or restart it. **Jaeger: Connection Settings** selects the local
Gateway URL; an optional model setting applies to new requests only. Empty model
means the Gateway/session chooses. Never put credentials in the URL. This initial
client rejects non-loopback URLs; remote access requires a separate authenticated
deployment, not exposing the unauthenticated Gateway.

## Behavior and boundaries

- Select an existing Gateway conversation or create a focused one. Histories are
  fetched from the owner, not copied into a new transcript database.
- Send, stream Markdown, inspect compact activity, approve/deny,
  request cancellation, reload history and reconnect. Enter sends; Shift+Enter
  inserts a newline; IME composition does not submit. Long content wraps; code
  scrolls horizontally. Colors and focus rings follow the IDE theme.
- Pending request IDs persist in IDE workspace storage keyed by Gateway URL;
  drafts stay in webview state. State is outside the source tree. Failed admission
  never triggers blind automatic resend. An ambiguous missing receipt needs
  investigation; the client intentionally retains its pending identity.
- Reconnecting observes an existing request. Closing the panel stops observation,
  not the owner's work. EOF is not completion; a durable receipt is required.
- Shared identity/knowledge remain backend responsibilities. Conversations retain
  their own transcript and focus; no indiscriminate cross-session merging or
  simulated personality controls are added here.
- Attachment registration and model selection use the Gateway contracts. The
  orchestration client methods exist, but the panel does not yet expose a
  qualified real-worker task flow. There is no automatic context forking or live
  observation of turns started in other clients. Refresh fetches other clients'
  completed history. Stop only
  targets the request ID this client knows, never unrelated work.
- Diagnostics report the endpoint/version/selected ID, not prompts or secrets.
  No generic shell/file/command bridge is exposed to webview content.

## Verification

```sh
node --test jaeger_ai/interfaces/ide/tests/client.test.js
dev/scripts/run_tests.sh --integration dev/tests/jaeger_ai/core/test_ide_gateway_client.py
```

The Python test owns an isolated real Gateway with a scripted provider and runs
the JavaScript client through it. It does not use the operator's daemon or paid
models. UI/host acceptance and real-provider behavior must be reported separately.
See `VERIFICATION.md` for the latest measured results and external artifact paths.

## Design/maintenance

`extension.js` adapts IDE messaging and settings; `conversation.js` owns only
client projection/observation; `gateway.js` implements HTTP/SSE. `media/` is the
presentation. Stream snapshots are frame-batched, events reduce into one ordered
timeline, and keyed rows keep settled DOM stable. There is no agent execution in
the extension. Keep future worker,
task, memory and fork logic behind owner APIs, shared with Web and Mac settings.
Large-history virtualization is a measured follow-on. Never render provider/tool
HTML directly.

API references: https://code.visualstudio.com/api/extension-guides/webview and
https://code.visualstudio.com/api/working-with-extensions/publishing-extension.
