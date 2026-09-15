# WebUI redesign prompt audit

Date: 2026-09-15

## Intent

Make a submitted chat reliably reach a terminal response in the current page, keep the
Hermes WebUI replaceable, give Jaeger one checked native-runtime contract, and make the
integration reproducible without disturbing the operator's finance work or live services.

## Confirmed problems

1. **A submitted answer can remain invisible until refresh.** Production logs show
   successful `POST /api/chat/start` requests for which the affected browser never opened
   the matching `GET /api/chat/stream`. The native runs completed and their replies were
   persisted. A disposable curl client attached to the same stream endpoint and received
   token, completion, and end events.
2. **The browser can exhaust its HTTP/1.1 connection budget.** Each page keeps two optional
   sidebar EventSources open in addition to the chat stream. The affected client was a PWA,
   and extra tabs multiply those connections. This explains the observed successful POST
   followed by no stream GET.
3. **The Hermes native adapter was implemented through two monkey patches.** One replaced
   an agent method; the other wrapped the adapter factory. Neither checked the upstream
   protocol when the adapter was assembled.
4. **Native `/v1/runs` does not restore history from `session_id`.** The installed Hermes
   API restores history for its separate chat endpoint, but initializes a Runs request with
   empty history unless the request supplies it. Jaeger's adapter must bridge this until
   Hermes fixes the Runs handler.
5. **The WebUI assembler is drift-prone.** It silently ignored missing overlays, named
   patches already folded into the pin, included a conflicting capabilities patch, and
   rewrote `docker_init.bash` by replacing one exact string.
6. **The pinned WebUI commit is not fetchable from its configured remote.** A clean
   submodule initialization cannot currently retrieve `0c79c12bd3831ca99dc526788cfa9847de7d0d31`.
7. **Container builds lose the WebUI version.** The archive excludes `.git`, and the live
   8787 service reports `webui_version: unknown`.
8. **There is no machine-readable version handshake on Jaeger Gateway or native Runs.** The
   live 8810 and 8645 services return 404 for `/version`.
9. **The Dispatcher sidecar is started once in the background.** A sidecar crash leaves its
   panels unavailable until the WebUI container is restarted.
10. **Incomplete backend registration can wedge a session.** Hermes and OpenClaw production
    `Runs` managers were built without reconcilers. An ambiguous native result therefore kept
    the durable ownership row while the only escape hatch raised “not supported.”
11. **Two recovery rules amplify failures.** HTTP 400/404 responses were classified as
    transient, allowing unsafe retries, and the MCP credential was resolved at import time,
    so provisioning it later could leave the process on its degraded path.
12. **Gateway defaults duplicated topology and host-specific addresses.** The daemon did not
    consume `contract/ports.py` and embedded operator-specific WebUI/Ollama hosts.
13. **Three controls advertised behavior they did not have.** The Swift reaction button had
    an empty action; WebUI Avatar and Work tabs only changed a title and displayed a notice.

## Prompt corrections

- Port 8790 currently reports `exp-v0.52.264-15-g0c79c12b-dirty-20fcd707`; only the 8787
  container reports `unknown`.
- The prompt's automatic toolless Gateway fallback description is stale in the current tree.
  Ordinary lead turns already fail closed when native MCP has no confirmed result. Ollama is
  limited to explicit `text_only` sessions and specialists. The unsafe 3B implicit default is
  removed; text-only mode now requires an explicit model setting.
- Moving browser routes directly to Gateway 8810 is incomplete. Gateway binds loopback and
  browser static requests cannot add its bearer credential. The deployable path is browser
  → authenticated WebUI edge on 8790 → Gateway on 8810 → backend. A future proxy change
  must define that edge and its authentication before implementation.
- A fully patch-free pin cannot be published in this task without first publishing the
  corresponding Hermes fork commit. Pointing the parent repository at a local-only commit
  would make clean checkouts even less reproducible.

## Deliverables

1. Browser stream-continuity extension that gives an active turn priority over optional
   sidebar EventSources and restores them after the last terminal event.
2. One composition-based native adapter with required-route and factory checks, native
   SessionDB history restoration, roundtable resume compatibility, and `/version`.
3. Jaeger Gateway `/version` endpoint with semantic component and protocol versions.
4. Deterministic WebUI assembler: explicit required overlays, no source string replacement,
   version stamping, and a supervised Dispatcher sidecar.
5. Removal of folded, conflicting, and obsolete overlay artifacts plus current integration
   documentation.
6. Two upstream-ready fix drafts for Runs history and false truncation handling.
7. An ordered migration plan that keeps the current service alive until a staged image and
   authenticated edge contract pass.
8. Evidence that the change is isolated from the 68-entry finance working tree.
9. Complete framework registrations for Jaeger, Hermes, and OpenClaw, including durable
   reconciliation and safe release of ownership only after terminal evidence.
10. Runtime MCP credential lookup, correct transient HTTP classification, shared port
    defaults, and hidden unfinished controls.

## Verification plan

1. Run the browser lifecycle harness and JavaScript syntax check.
2. Run native adapter, launcher, workspace, and Gateway endpoint contract tests.
3. Assemble a fresh context from the pinned archive; require every patch to apply and prove
   the version and all extension/supervisor files are present.
4. Run the existing WebUI proxy and relevant regression tests.
5. Probe the live 8790/8810/8645 services read-only and run a disposable real Runs turn;
   delete the disposable session afterward.
6. Scan the isolated branch for old monkey-patch imports, stale patch names, in-tree caches,
   and JavaScript syntax errors.
7. Compare `git diff main...HEAD` and the worktree delta against the original main checkout;
   fail if any path overlaps the finance work.

Image rebuild, deployment, service restart, remote fork publication, and upstream PR creation
remain review gates. They are not necessary to make the repair concrete and testable.
