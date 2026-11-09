# Standalone foundations

Jaeger's canonical macOS shell hosts the same React UI as the authenticated web client. The standalone app includes its Python interpreter and dependency environment, source snapshot, compiled UI, Node, Chromium and Steel Browser. Operator data and credentials stay in the existing operator state directory. Cloud model providers still require an account and network connection; optional external coding products remain integrations.

## Ownership and migration

| Area | Existing owner and evidence | Change | Validation |
|---|---|---|---|
| Shell, chat and panels | StableDemo, ConversationWorkPanel, canonical Swift host | Retain shell and mounted chat; expose browser workspace | UI navigation and persistence checks |
| Settings | App.tsx settings controls; draft SettingsWorkspace was routed by StableDemo | Route Settings to existing real controls within the shell; retain unused draft source pending cleanup review | Settings route and mounted-chat regressions |
| Sessions, approvals, events and execution | JaegerGatewayApp and GatewaySessionStore | Retain sole authority; browser feature registers on the existing Gateway | Auth, isolation, same-session transport tests |
| Browser | Existing agent browser tool and external OSS browser integrations | Gateway-owned per-conversation Steel process; native agent tool uses admitted conversation; explicit jaeger.browser MCP tool | Real Chromium, frame streaming, page interaction, profile isolation, shutdown |
| Browser UI | codex-ui-kit 0.1.2, MIT | Dependency with narrow Jaeger transport adapter and scoped styles | Visible UI plus user and agent interaction with one page |
| App packaging | Swift shell previously used an external launcher/venv | Bundle interpreter, dependencies, source and UI; launcher resolves relative to app; seal revision | Relocation, isolated imports, codesign, installed process/revision checks |
| Qt SQL plugins | Installed PySide6 ships unrelated server database plugins; no Jaeger QtSql/QSql consumers | Packaging omits Mimer, ODBC and PostgreSQL plugins; retains SQLite and other PySide6 functionality | Native dependency closure; exclusions recorded in artifact manifest |

No runtime, event bus, identity, memory or planner authority is replaced. No live operator data is copied into the artifact. The pre-existing dirty checkout was saved separately before this integration. No unrelated application is stopped during deployment.

## Reused code

- `codex-ui-kit@0.1.2`: pinned in the UI lockfile; MIT and dependency notices included in `public/licenses`.
- Steel Browser `c8aebf9462187fc5a80b587ba2086900aecab236`: Apache-2.0 source and dependencies retained in the browser bundle. `packages/jaeger-browser` documents three bounded upstream integration patches and route adaptation.
- Official Node 22.23.2 archive with verified SHA-256; Playwright Chromium revision recorded in browser manifest.
- Native libraries copied with SHA-256 provenance and distribution notices, with Mach-O dependencies relocated inside the app.
- Proprietary Codex/ChatGPT program code is not shipped.

## Build

Build outside the checkout, preferably under `/private/tmp` (Finder metadata in Documents can invalidate macOS code signing):

```
npm --prefix jaeger_ai/interfaces/ui ci
npm --prefix jaeger_ai/interfaces/ui run build
python3 packages/jaeger-browser/build.py --help
# Build the browser bundle using that script's explicit output arguments.
~/.jaeger/venv/bin/python -B scripts/build-standalone-macos.py \
  --output-root /private/tmp/jaeger-standalone-candidate \
  --browser-bundle /absolute/path/to/browser-runtime \
  --dependency-python ~/.jaeger/venv/bin/python
```

The Python dependency environment is an explicit build input, recorded in `dependency-manifest.json`; this is a sealed environment snapshot, not yet a fully reproducible wheel build. The builder rejects editable path files and missing native dependencies. Optional external native inputs can be provided with `--native-dependency-root`. The resulting app is locally ad-hoc signed; public distribution still needs Developer ID signing/notarization.

## Acceptance

Run the repository verification pipeline and focused UI, Swift, stack and browser tests. For the real browser integration test set `JAEGER_TEST_BROWSER_BUNDLE` to the built bundle. Test the actual WebUI handler, since its request-body cleanup must know the proxy consumed the POST body. Verify user pointer events and agent actions affect the same page, settings preserve the shell, and two conversations stay isolated.

For deployment, stop only the owned Jaeger stack, retain the prior app/source for rollback, install the candidate, launch its bundled CLI/services, open the native app, and compare running Gateway revision and served UI hashes to the candidate. Confirm a real provider response is persisted before calling the installed update verified.

An owner-local build may include an existing provider executable with `--provider-cli grok=/absolute/path/to/grok`. The executable is copied into runtime/bin, checksummed in provider-runtimes.json and preferred on the service PATH. Credentials stay in the provider's existing account store. This does not import proprietary code into the repository or assert public redistribution rights.
