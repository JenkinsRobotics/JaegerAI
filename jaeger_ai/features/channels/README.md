# Channels

Multi-channel ingress for Jaeger. **Jaeger stays the reasoner**; Discord /
Telegram / iMessage / future WhatsApp / Signal / Matrix are transport faces.

## Today

| Surface | Location | Status |
|---|---|---|
| Discord | `jaeger_ai/plugins/discord/` | Live plugin |
| Telegram | `jaeger_ai/plugins/telegram/` | Live plugin |
| iMessage | `jaeger_ai/plugins/imessage/` | Live plugin |
| Slack | gateway messaging stub | Thin |
| WhatsApp / Signal / Matrix / … | this feature | Catalogued; adapters TBD |

## This package

- `adapter.py` — thin `ChannelAdapter` protocol + message dataclasses
- `catalog.py` — bundled channel catalog (OpenClaw-inspired ids/aliases)
- `registry.py` — register/lookup adapters without replacing plugins
- `PORT.md` — donor paths and next slices

Do **not** replace working plugins in place. New platforms land under
`jaeger_ai/features/channels/<platform>/` and register here.

## Gateway/shared UI status

`GET /v1/channels` and Settings→Channels show this Gateway process's existing bridge/adapter registrations, catalog maturity and observed transport thread state. Registration is not connection-health or delivery evidence. Reads never start/probe a bridge, inspect credentials or send a message; other processes are unobserved. Current read scope applies; prefixed peers cannot read the global inventory. Connect/disconnect, durable bot binding and a correlated Gateway-native incoming handler still require implementation; the legacy standalone messaging daemon is not an automatic fallback.

Shared plugin callback adaptation selects `(text, session_key=...)` or legacy `(text)` using signature binding before invocation. A handler `TypeError` after an effect is propagated once, never treated as a reason to call again. Caller trust, allowlists, approval behavior and provider configuration are unchanged. Local fixtures exercise this without SDK startup, external credentials or OS Messages access.
