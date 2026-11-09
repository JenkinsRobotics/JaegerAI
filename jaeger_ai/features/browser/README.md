# Shared conversation browser

The existing Gateway owns one private Steel/Chromium worker per conversation
(up to four simultaneously). All UI and agent actions target that worker's
selected tab. Existing Gateway authentication, session restrictions, turn
permissions and global Stop apply. Native browser tools retain their existing
tool approval decorators before entering this transport.

POST `/v1/sessions/{id}/browser/action` starts or operates a worker.
GET `.../viewer` returns the upstream viewer with a same-origin WebSocket URL.
GET `.../cast` carries interactive frames and requires the `turn` scope.
WebUI access also goes through the existing login gate; cross-origin viewer
control is rejected. Agent tools cannot supply the owning session identity.

Packaging is in `packages/jaeger-browser`. Runtime state stays outside source.
