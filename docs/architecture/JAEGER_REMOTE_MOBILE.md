# Jaeger remote phone access

The iPhone is a remote interface to the **same** resident Jaeger on the Mac.
It is not another Agent, EntityRuntime OWNER, Event Fabric, or memory world.

## Topology

```text
Mac — Resident Gateway OWNER 127.0.0.1:8810
        │
        same Jaeger
        │
      WebUI 127.0.0.1:8790
        │
      Tailscale Serve (HTTPS, tailnet only)
        │
      iPhone Safari / installed PWA
```

Gateway, Bridge (`127.0.0.1:8791`), and MCP stay on loopback.
Do not use Tailscale Funnel, router port-forwarding, or public listeners.

## Trust boundary

Tailscale Serve terminates HTTPS and proxies to loopback WebUI.

The WebUI process therefore sees **127.0.0.1** as the TCP peer. Source-IP
enforcement at the WebUI is loopback in this topology.

The enforceable remote boundary is:

1. membership in the operator tailnet
2. WebUI authentication (password, pairing token, or passkey)
3. session cookie + CSRF on mutating routes
4. Jaeger Authority for tools

`RemoteAccessPolicy` remains fail-closed for any surface that *does* see a
Tailscale CGNAT peer (adapter `--allow-remote`, bearer token). Forwarding
headers are not trusted.

## Commands

```text
jaeger remote enable
jaeger remote disable
jaeger remote status
jaeger remote doctor
jaeger remote pair
```

`enable` inspects Tailscale, requires WebUI auth, publishes only the WebUI
through Serve, and prints a one-time pairing URL / QR.

If Tailscale is missing or logged out, enable stops for that human action
and continues after `jaeger remote enable` is run again.

## Pairing

`jaeger remote pair` issues a high-entropy, 15-minute, single-use token.
The token is stored as a SHA-256 digest only. It is exchanged for a bounded
WebUI session and cannot authorize Gateway/tool execution by itself.

Passkeys remain available on the HTTPS origin (`HERMES_WEBUI_PASSKEY=1`).

## Devices

Authenticated `GET /api/remote/devices` lists sessions (token prefixes only).
`POST /api/remote/devices/revoke` and `revoke-all` drop phone sessions.

## PWA

Install via Safari → Add to Home Screen. Manifest name is Jaeger; viewport
uses `viewport-fit=cover`; chat/code/approvals constrain on narrow width.

## Disable

`jaeger remote disable` turns the policy off and removes the WebUI Serve
route. Local loopback WebUI and Gateway remain.

## Threat model (short)

| Threat | Control |
| :--- | :--- |
| Public internet | No Funnel; Gateway loopback-only |
| LAN scrape of WebUI | Auth required after enable; prefer WebUI bind 127.0.0.1 |
| Stolen pairing URL | 15 min, single use |
| CSRF | `X-Hermes-CSRF-Token` on mutating API |
| Tool abuse | Authority confirmation, not phone login |
| Mac asleep | Phone shows unreachable; no cloud Jaeger |

## Troubleshooting

- `jaeger remote doctor` — live checks
- `tailscale status` — logged in?
- `tailscale serve status` — HTTPS → `http://127.0.0.1:8790`
- `lsof -nP -iTCP:8810 -sTCP:LISTEN` — must be `127.0.0.1`
- Phone: Jaeger is currently unreachable → Mac awake? Tailscale up on both ends?
