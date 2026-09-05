# Jaeger-owned Hermes WebUI integration

Customizations belong here, not in the standalone ARES or Hermes WebUI repos.
`upstream.patch` preserves the existing profile, gateway, command and UI fixes
against the pinned `vendor/hermes-webui` submodule. `jaeger_ollama.py` provides
independent Mac/Rack Ollama inventories, complete model tags, and exact routing.

Run `.venv/bin/python scripts/prepare-hermes-webui.py` from JaegerAI to create
a disposable build context from the pinned upstream plus these changes. The
script checks patch applicability before applying it. Build that directory's
Dockerfile for a fresh image. Do not build an unpatched donor checkout.

For the incremental dependency image, build from the printed staging directory:
`container build -f Containerfile.jaeger -t hermes-webui:jaeger-ollama-hosts-verified-20260904 .`
The tar overlay and build-time assertions guard against incomplete directory
copies in the Apple Container build context. Compare hashes in the resulting
image before replacing a running container. The live container also has this
overlay in `/apptoo`; stop/start preserves it, but recreation must use the
verified image or reapply the overlay.

## Verified September 4, 2026

- 40 parent tests: adapter protocol/EOF, host routing, incident mode, failed-member
  isolation, supervisor address discovery, MCP and A2A contracts.
- 34 upstream profile tests in the staged tree, using JaegerAI's Python and the
  configured Hermes Agent checkout (the system Python is too old).
- Real simultaneous WebUI chats and second turns for Hermes, Jaeger, OpenClaw,
  and Roundtable; the earlier concurrent run exposed incorrect cross-profile
  routing, now fixed by reading gateway config independently for each worker.

## Remaining limitations

- The model picker routes Hermes requests to the selected Ollama host. Native
  Jaeger/OpenClaw gateway adapters still use their configured runtime models;
  per-chat picker overrides are not wired into their native session APIs yet.
- Roundtable streams member-level results as they arrive, not every model token.
- Cancellation does not yet reliably stop already-dispatched native tool work.
- Supervisor health is a transport check, not proof that an LLM turn succeeds.

Runtime profile config has `model.provider: ollama`, the selected daemon's
`model.base_url`, and shared `ollama_hosts` entries (`rack` and `mac`, each with
`label` and `base_url`). Model picker IDs are `@ollama-rack:model:tag` or
`@ollama-mac:model:tag`; tags must never be split at the last colon. Cloud
proxy tags and downloaded models are labeled separately within each host.
Discovery does not route around an unavailable host or borrow its peer's list.

Adapters must emit `message.delta` with `delta`, then `run.completed`,
`run.failed`, or `run.cancelled`, and close the SSE connection. Transport
heartbeats are not evidence that an LLM is progressing. Long work is not given
a fixed total time limit; do not infer an outage from a slow model response.
