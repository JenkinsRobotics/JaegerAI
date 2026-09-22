# WebUI runtime truth

The WebUI is a client of canonical Jaeger runtime state. Hermes Agent remains
an explicit selectable runtime. Fresh product default is Jaeger.

## Sources

| Surface | Producer |
| :--- | :--- |
| Frameworks | `jaeger_ai.contract.frameworks` + health probes; `GET /v1/runtime/frameworks` |
| Models | `canonical_runtime_inventory()`; WebUI `/api/models` |
| Capabilities | `jaeger_ai.core.runtime.truth.capability_snapshot`; `GET /v1/runtime/capabilities` |
| Attachments | Gateway `attachments` table; `POST/GET /v1/sessions/{id}/attachments` |

`default` remains the upstream Hermes profile name. It must not be the
Jaeger product default. Product default profile/runtime is `jaeger`.

## Live matrix (operator, 2026-09-21)

| Test | UI / API | Gateway | Runtime evidence | Result |
| :--- | :--- | :--- | :--- | :--- |
| Fresh default | `/api/profile/active` name=jaeger | session profile=jaeger | `JAEGER-DEFAULT-PASS` | PASS |
| Kimi selection | catalog default kimi-k2.7-code:cloud | jaeger session | `KIMI-SELECTION-PASS`; REACT PASS | PASS |
| Hermes switch | profile=default | session profile=default | `HERMES-ROUTE-PASS` | PASS |
| Image attachment | `/api/upload` PNG | attachments row | `VISION-TOKEN-7421` | PASS |
| Text attachment | `/api/upload` txt | attachments row | `ATTACHMENT-TOKEN-9981` | PASS |
| Capability inventory | `/v1/runtime/capabilities` | entity OWNER resident | kimi REACT PASS; glm REACT FAIL; Anthropic not configured | PASS |
| CSRF missing | 403 | — | keep-alive next request aligned | PASS |
