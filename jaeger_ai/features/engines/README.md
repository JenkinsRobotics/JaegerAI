# engines

Hermes and OpenClaw as coordinated engines inside Jaeger (J-083).

- `catalog.py`: read-only view of each engine's own skills and memory, served at `GET /v1/engines/catalog`. Never writes engine state; files are size-capped and credential-looking files are skipped.
- `embed_proxy.py`: loopback proxy that lets the WebUI embed the Hermes dashboard and OpenClaw gateway UIs.

Touchpoints: Gateway routes, WebUI Agents › Hermes / OpenClaw tabs.
