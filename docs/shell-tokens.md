# Shared Mac + WebUI shell tokens

Single product face: **Jaeger** (not Hermes-first). Mac app and WebUI share
nav concepts and the Gateway `:8810` agents catalog.

## Brand

| Token | Value | Mac | WebUI |
|-------|-------|-----|-------|
| `brand.name` | Jaeger | window / menu | `document.title`, `#appTitlebarTitle` |
| `brand.lead` | Assistant | default agent | `native:jaeger` display_name |
| `brand.accent` | `#3aa0ff` | `Term.accent` | CSS `--accent` / branding |
| `brand.canvas` | `#0B0E14` | `Term.canvas` | dark theme ground |
| `brand.ink` | `#DDE2EA` | `Term.ink` | `--text` |

## Nav concepts (parity)

| Concept | Mac | WebUI |
|---------|-----|-------|
| Chat | Chat tab / stage | rail `data-panel="chat"` |
| Agents | sidebar **AGENTS** from `GET :8810/v1/agents` | branding `#jaegerAgentsSection` via `/api/agents` proxy |
| Settings | Agent Settings HUD / menu | rail `data-panel="settings"` |
| Sessions | RECENT sidebar | `#sessionList` |

## Agents catalog contract

- Source of truth: Gateway `GET /v1/agents` (`model: grok_bot_shape`).
- WebUI proxies as `GET /api/agents` (server-side to loopback `:8810`).
- Activate: `POST /v1/agents/{id}/activate` (Mac `GatewayClient`, WebUI branding).
- Standing specialists (Jaeger-native): `native:surfaces`, `native:gateway`, `native:everyday`.
- Lead: `native:jaeger` (`Assistant`, metadata.role=`lead`).
- Handoff stub: `POST /v1/agents/{id}/handoff` + approvals reuse.

## Locked endpoints

- Ollama `http://192.168.64.1:11434`
- WebUI `http://100.74.2.15:8790/`
- Gateway `http://127.0.0.1:8810`

Do not treat `:8813` as the chat spine.
