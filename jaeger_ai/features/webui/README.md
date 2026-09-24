# Jaeger WebUI

**Classification:** CURRENT REFERENCE
**Current execution entry point:** [`docs/CONTINUE_FROM_HERE.md`](../../../docs/CONTINUE_FROM_HERE.md)

The WebUI is a browser client of one persistent Jaeger Gateway. It does not own
execution, entity identity, durable sessions, tools, approvals, or memory.

## Current topology

```text
Browser (:8790)
  → WebUI HTTP/SSE server
  → Jaeger Gateway (:8810)
  → resident EntityRuntime / JaegerAgent
  → durable Gateway session, request, approval, and event records
```

The public launcher is `scripts/run-jaeger-webui.sh`. It resolves state through
`operator_state_root()`, starts the browser server on `:8790`, and sets
`JAEGER_GATEWAY_URL` to `http://127.0.0.1:8810`.

The browser’s chat route is `/api/chat/start`, but that route is a WebUI
adapter/proxy. Its current default is the Gateway:

- `api/gateway_chat.py::webui_chat_backend_mode` returns `gateway` unless an
  explicit Gateway selection or URL is present.
- The in-process WebUI runtime and `:8791` runner are legacy paths, selected
  only when `JAEGER_LEGACY_PATHS` is explicitly enabled.
- `api/gateway_mirror.py` projects Gateway conversations into the WebUI’s
  local cache. The Gateway remains the owner of titles, transcripts, and
  request receipts.

By default the WebUI hides tabs that read legacy Hermes systems rather than
Jaeger state: tasks, kanban, skills, memory, profiles, todos, insights, and
logs. It offers only the `jaeger` profile. `JAEGER_LEGACY_PATHS=1` re-enables
the old surfaces for diagnosis; it is not a release mode.

## Layout

| Path | Role |
| --- | --- |
| `server.py` | Browser HTTP server and SSE host |
| `api/` | Browser API, Gateway proxy, session mirror, settings, uploads, and legacy routes |
| `static/` | Browser HTML, JavaScript, CSS, and localization |
| `adapter/` | Legacy runner and bridge adapters |
| `service/` | WebUI lifecycle, profile layout, and state preparation |

`jaeger_ai/assets/` remains the single extension mount for browser scripts.
The browser source retains Hermes WebUI lineage and license notices, but the
implementation is first-party Jaeger source.

## Verification

```bash
dev/scripts/run_tests.sh --unit \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_one_execution_path.py \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_gateway_mirror.py \
  dev/tests/jaeger_ai/features/webui/server_regressions/test_gateway_stream_admission.py
```

These tests prove the Gateway default, mirror semantics, admission, attachment
scope, terminal usage, and tool/activity event boundaries. They do not prove a
configured live provider or a physical phone. Live acceptance belongs to the
Gateway/WebUI golden journey in `docs/CONTINUE_FROM_HERE.md`.
