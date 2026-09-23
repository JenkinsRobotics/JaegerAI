# Operating JaegerAI: state, upgrades, recovery

For operators running JaegerAI on their own machine. Every behavior below is
intended to be checked against its named tests; historical test results do not
certify the current installed build.

## Current release qualification

The [master personal-release plan](architecture/GROK_PERSONAL_RELEASE_PROMPT.md)
defines the September 28 companion-assistant RC scope and required evidence.
It is **not yet qualified**. Do not infer live voice, remote phone access or IDE
worker automation from available source files. Final handoff must identify the
external `.app` and VSIX artifacts, exact startup/configuration, enabled features,
remaining limitations and activation/rollback steps. No live installation was
changed by the planning/review passes. The Swift build script now defaults to
`~/.jaeger/apps/swift-build` (override `JAEGER_SWIFT_BUILD`) and supports read-only
`--print-build-dir`. CLI launchers pass the checkout via `JAEGER_REPO`. External
path tests pass; actual `.app` build/GUI launch is still an RC qualification task.

## Where state lives

JaegerAI keeps all runtime state outside the source checkout. The state root is
chosen in this order:

1. `JAEGER_STATE_DIR`, if set and not blank. Used exactly as given.
2. `JAEGER_HOME`, if set: state goes in `$JAEGER_HOME/.jaeger_ai`.
3. Otherwise `~/.jaeger`.

The Python environment lives in `$JAEGER_VENV` (default `~/.jaeger/venv`).
`./jaeger`, `run.sh`, `scripts/run-jaeger-webui.sh` and the test runner all
use it; none of them falls back to a `.venv` inside the checkout.

**Common mistake.** The one-line installer uses `JAEGER_HOME` to mean *where
to clone the code*:

```bash
JAEGER_HOME=/opt/jaeger curl -fsSL .../install.sh | bash
```

If that variable stays exported in your shell profile, JaegerAI would put its
state inside the checkout. It refuses to start instead, and says so. Fix it by
unsetting `JAEGER_HOME` (state then goes to `~/.jaeger`), or by setting
`JAEGER_STATE_DIR` to where you want state kept.
(`test_instance_resolver.py::test_jaeger_home_inside_a_checkout_raises_instead_of_nesting_state`)

**Scratch instances.** Set `JAEGER_STATE_DIR` to a fresh unique directory outside
the checkout for the Gateway and all its clients. The WebUI launcher honors the
same variable. This isolates resolver-backed stores; it is not proof that every
legacy path avoids live state. Use the isolated test runner and its disk checks,
and explicitly owned ports/sockets so tests do not connect to operator services.

## Upgrading from the old `.jaeger_os` layout

When `JAEGER_HOME` is set and an old `$JAEGER_HOME/.jaeger_os` directory
exists without `.jaeger_ai`, the first start migrates it automatically:

1. It takes a lock, so two processes cannot migrate at once.
2. It makes a verified backup. Databases are copied with SQLite's backup API,
   which includes data still in the write-ahead log.
3. It copies the backup into a staging directory next to the destination and
   checks every file hash, every database's integrity and every table's row
   count.
4. It activates the result with a single rename. You see either the old state
   or the complete new state, never a mixture.

The old `.jaeger_os` directory is left untouched. Delete it yourself once you
are satisfied. The backup and a manifest are kept in
`$JAEGER_HOME/.jaeger_ai.migration/`; the manifest records file names, sizes
and hashes, never file contents or secrets.

**If a migration stops** (crash, power loss, full disk, locked database):
nothing is lost. Start JaegerAI again and it resumes from the recorded phase.
If it cannot finish, it refuses to start rather than running on an empty
state, and the error names the manifest to inspect.
(`test_state_migration.py`: crash at each of seven phases, corrupt and locked
databases, low disk, concurrent migrators)

**If both `.jaeger_os` and `.jaeger_ai` already hold data**, the existing
`.jaeger_ai` is treated as your live state and the old directory is ignored.
Nothing is merged.

## Backups

```bash
jaeger backup     # zip one instance (secrets and regenerable caches excluded by default)
jaeger restore    # unzip into ~/.jaeger/instances/<name>/; refuses to overwrite without --force
```

## Cancelling work

Cancelling a turn (the stop button, or `POST /v1/sessions/{id}/cancel`)
interrupts that request only. Other sessions keep running.

- A cancel while the model is thinking stops the request immediately.
- A cancel while an approval prompt is open closes the prompt. Approving it
  afterwards is rejected, and the action does not run.
- Work that already completed stays done and recorded.
- If the process died in the middle of an action, the request is reported as
  **outcome unknown** rather than guessed. Check what happened, then use
  `POST /v1/sessions/{id}/reconcile` to settle it.

(`test_gateway_owned_process_contract.py`, `test_request_cancellation.py`)

## Retrying a request

A client that retries a turn with the same `request_id` gets the original
result back; the work is not run twice. The model, provider, attachments and
options are fixed when the request is accepted, so changing the session's
model afterwards cannot change a request already in progress. Reusing a
`request_id` with different text or choices returns HTTP 409.
(`test_gateway_admission_snapshot.py`)

## Health checks

```bash
jaeger doctor                              # dependencies, permissions, install health
curl -s http://127.0.0.1:8810/health       # Gateway (note: /health, not /v1/health)
jaeger onboarding status --json            # first-boot state
```

## Not yet qualified

- The native app talks to both the Gateway (`:8810`) and `jaeger bridge`, and
  each can run the assistant. Converging them is planned work.
- A full install that resolves every dependency from PyPI has not been
  qualified on a clean machine.
- Swift `DispatcherLiveTests` drive `launchctl` against real services and are
  skipped until they use an isolated fixture.
