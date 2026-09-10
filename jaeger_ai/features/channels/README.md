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
