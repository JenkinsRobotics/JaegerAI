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

## Activation notes (operator, 2026-09-21)

Canonical origins:

- Local WebUI: `http://127.0.0.1:8790` (loopback only after `jaeger remote enable`)
- Remote: `https://matthews-mac-studio.tail80f206.ts.net:8443`

Retired Serve routes: `:443 → 8787` and `:8444 → 8788` (dead listeners).

Safari/iOS: this agent cannot delete an installed Home Screen PWA. Re-open the Jaeger PWA so service worker `jaegerpd7` replaces `jaegerpd6`. Unrelated Safari data was not touched.

Physical iPhone Safari/Face ID/Add-to-Home-Screen was not completed in this pass. Pairing and campaign turns were exercised over the canonical HTTPS origin with an iPhone user-agent.

## CSRF (cookie vs bearer)

Authenticated cookie mutations require `X-Hermes-CSRF-Token`. That includes session create/delete, conversation turns, approval respond, uploads, and remote-device revocation.

GET/HEAD are not CSRF-gated.

Bearer-only infrastructure calls (Authorization: Bearer, no session cookie) follow the existing bearer policy and are exempt from this CSRF gate. A request that carries both a valid session cookie and a bearer token is treated as a cookie session and still needs the CSRF token.

`/api/remote/pair` is CSRF-exempt because it exchanges a one-time pairing token before a session cookie exists.

## Phone-access close-out (2026-09-21)

Operator entity remained `jaeger-entity-7615957f0fa6`. Canonical origin remained `https://matthews-mac-studio.tail80f206.ts.net:8443`.

Live HTTPS proofs (iPhone user-agent):

| Gate | Result | Evidence |
| :--- | :--- | :--- |
| Cookie + no CSRF | 403 | `POST /api/jaeger/sessions` |
| Cookie + invalid CSRF | 403 | isolated retry after Tailscale 501 |
| Cookie + valid CSRF | 201 | session `2e7c307c7ea9494cbde5cf0a52eab257` |
| Unauthenticated | 401 | `GET /api/jaeger/runtime/status` |
| Write + disk verify | PASS | `workspace/mobile-verification.txt` = `MERCURY-VERIFIED`; `verification.completed` `vrf-de85eae62d` `objective_verified` `disk_probe`; tools `tls-68738ae23f` / `tlc-7366731655`; Gateway terminal idle |
| Stock approval approve | PASS | `GET /api/approval/pending` showed `files.write_file` + target; `POST /api/approval/respond` `{"ok": true, "choice": "once"}` `approval_ed933eda29c6` |
| Stock approval deny | PASS | `approval_5712ea699b85` denied; `should-not-exist.txt` absent |
| PNG upload → Gateway session | PASS | `store: gateway`, `is_image: true`, `workspace/uploads/2e7c307c7ea9494cbde5cf0a52eab257/75bd874e20_phone-upload.png` |

Resident OWNER turns use in-process ReAct (same production verification as Round 6). WRITE_LOCAL parks on the Gateway approval bus; the stock WebUI approval card polls that bus through `/api/approval/pending`.

Tailscale Serve HTTP/1.1 connection reuse can surface as `501 Unsupported method ('{json}POST')` after a 403. That is proxy keep-alive, not a CSRF logic failure. Clients should send `Connection: close` (the WebUI fetch interceptor already attaches CSRF).

Verdict remains **PHONE ACCESS — NOT READY** until physical iPhone Safari / Add to Home Screen / passkey (Face ID) and a real Wi-Fi ↔ cellular reconnect are observed on the device.
