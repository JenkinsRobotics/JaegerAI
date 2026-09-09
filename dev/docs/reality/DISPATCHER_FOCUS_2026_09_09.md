# Dispatcher and Focus — implementation and operational evidence

## Implemented

- `core/runtime/dispatcher.py` owns a per-instance SQLite routing/report ledger. One WebUI session binds to native `dispatcher`; other Jaeger profile sessions route to separate `focus:<session>` agents. It never merges another conversation into the Dispatcher transcript.
- `main.py` resumes the Dispatcher's native history after restart and gives Focus agents a 16,384-token context cap and coding/research/audit/general tool bundles. Native persona, operator facts, permission handling and tool execution remain in Jaeger. Model overrides preserve each conversation and do not rewrite instance configuration.
- `core/sessions.py` protects the Dispatcher from ordinary session-retention pruning. Explicit session deletion is not overridden.
- The native bridge publishes Focus results before its terminal reply, rather than relying on a WebUI observer to stay connected. Full outputs remain in `dispatcher.sqlite3`; bounded, worker-attributed result excerpts are projected onto the native board. A completed turn is not proof that an entire objective was achieved.
- Bridge contract version 15 adds `dispatcher_memory`, projecting native SQLite operator facts, the existing JSON board and Focus reports. Skills use the existing native skill service; **106 skills** were returned by the running instance. Legacy `facts.json` is not treated as the active facts database.
- `jaeger.py` exposes authenticated `/v1/dispatcher`, `/bind`, `/skills`, `/memory` and `/models` routes under the Dispatcher namespace. Existing native run model/provider and structured-input wiring remains intact.
- `assets/jaeger_dispatcher.js` and `jaeger_webui_extensions.json` use Hermes' official extension mechanism. They add Dispatcher/Focus cues and Jaeger-owned memory/skills views. Other profiles retain their handlers. The extension does not overwrite upstream source or intercept global network functions.
- `features/hermes_webui/dispatcher_sidecar.py` implements the official token-v1 proxy boundary on container loopback port 8646. It validates the injected token and permits only its fixed native routes. The overlay assembler installs the extension and starts the sidecar alongside WebUI.

## Runtime verification

- Final full suite: **3,823 passed, 1 skipped**, one existing Discord `audioop` deprecation warning, 110.73 seconds. A preceding rerun caught a personal checkout path in the newly saved verification helper; it now derives that path from its own checkout, and the ownership guard and full suite pass.
- Entire interface suite after that move: **560 passed**, 31.94 seconds.
- Final bridge, native runs, Dispatcher and surface-contract checks after capability declarations: **132 passed**, 5.33 seconds.
- Syntax compilation: **836 Python source files** across `jaeger_ai` and workspace packages, excluding generated build/cache/virtual-environment trees. The extension JavaScript passes Node syntax checking. Its executable Node tests cover native panel routing, safe text rendering, immediate profile switching, persistent Dispatcher navigation, consent errors and disabled request replay.
- Live Dispatcher retained a fresh verification identifier across a separate Focus task. The Focus task emitted `read_file` start/completion events and quoted the README's first line. Its report appeared on the native board and was available to the Dispatcher's next turn without copying the worker transcript.
- Live structured base64 text attachment: native `read_file` returned its unique contents. The request selected **glm-5.3:cloud**, and the native session record stamped that model. The instance configuration hash remained unchanged.
- After a bridge restart, the pinned WebUI Dispatcher resumed the same conversation and recalled both the fresh identifier and the attachment worker's result. Events included `token`, `reasoning` and `done`.
- `jaeger doctor`: all preflight checks passed. `jaeger status`: bridge, adapters, native Hermes API, MCP, A2A, supervisor, WebUI and OpenClaw containers running; Ollama reachable. Honcho remains intentionally paused.
- The running WebUI extension diagnostic reports its manifest loaded, two scripts, one sidecar, and no warnings. The sidecar's live loopback health endpoint responds successfully.
- Vendor submodule remains clean. Existing user changes, including previously staged reference-image removals, were preserved. Nothing was committed.

The first live prompt ambiguously requested “the word” and the model returned a previously stored codeword instead of the fresh identifier. An explicit fresh-identifier prompt succeeded. That result is retained as a model-behavior limitation, not presented as a passing first attempt.

## Operator setup still required

The official extension proxy requires WebUI authentication and explicit extension consent. This installation currently has authentication disabled and no consent for `jaeger-dispatcher`; a same-origin proxy request returns **403: Extension sidecar proxy consent required**. Its diagnostic posture is `local_unprotected`. No authentication or consent guard was bypassed.

In WebUI Settings, set **Access Password**, then approve **Jaeger Dispatcher and Focus** under **Extensions**. The user chooses the password; do not send it in chat. These settings are required by the pinned upstream `vendor/hermes-webui/docs/EXTENSIONS.md` token-v1 contract. The extension is installed and ready for that final step, but the authenticated browser-to-native panel flow is **not yet verified**.

Pinned Dispatcher WebUI session: `59abf41d213a`. Its existing sidebar entry can be opened and used for chat. Native Dispatcher session identity: `dispatcher`.

Resolve the current container address with:

```sh
./jaeger webui url --instance jaeger
```

At verification time, the Dispatcher page was `http://192.168.64.74:8787/session/59abf41d213a`. Container addresses can change on restart; the CLI and desktop URL resolver discover the current address.

Repeat the native continuity/tool/report probe with:

```sh
.venv/bin/python scripts/verify-dispatcher-native.py
```

This creates labeled verification work, consumes model tokens and leaves its reports for inspection.

## Limits and follow-up boundaries

- Focus agents have separate contexts and native agent objects, but the current bridge still serializes their execution. Concurrent voice responsiveness while a long Focus job runs is not proven. This is not a claim of a completed real-time voice scheduler.
- Focus reports describe terminal turns and retain worker-reported evidence. They do not independently verify every task claim or automatically certify an entire objective complete.
- The native panels currently expose memory and skills for reading; edits are not routed into Hermes fallback files. Existing panels outside the extension, notably scheduler/MCP settings on non-Hermes profiles, retain the limitations in the profile-switch audit.
- Direct image reasoning depends on the selected native model and available vision tools. The verified attachment case was a text file, not an image.
- OpenClaw model changes still await the separate pending native `operator.admin` scope decision. No scope was granted automatically.
- The first all-profile WebUI check exposed missing Roundtable member contributions in ordinary chat: only synthesis was displayed. The native table now streams readable per-member transcript sections while retaining richer native events. Regression tests passed, and the repeated two-turn WebUI check passed for all four profiles, including each Roundtable member’s answer. This establishes chat continuity, not parity for every optional panel.
- Extension JavaScript passed executable tests with a minimal DOM harness, and its actual injection/configuration was verified by HTTP. The authenticated browser panel flow awaits login/consent. No screenshot or visual-browser verification was performed.

## Deployment reproducibility and rollback

`scripts/prepare-hermes-webui.py` assembles the pinned upstream checkout, Jaeger-owned patches, extension assets and sidecar. The running container received verified files directly. The assembled image `hermes-webui:jaeger-dispatcher-20260909` was then built and its contents/startup checked in an isolated container. The managed Hermes recreation path now selects that image; 24 workspace/container-plan tests passed. The current container was preserved rather than replaced.

Current deployment backups are outside the repository under the macOS temporary directory: `jaeger-native-webui-backup-717b_o6m` (Python gateway/config files) and `jaeger-dispatcher-extension-backup-z8nzqijs` (container startup script). Native state remains in the instance and shared run directories; rollback must preserve it.
