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

## Configured inbox controls (source, not externally activated)

Existing admin/read routes now expose revisioned per-channel inbox-bot binding and explicit connect/disconnect for Telegram/Discord/iMessage. Connect reuses existing instance credentials plus a parsed nonempty existing allowlist; it cannot create credentials or change permissions. Registered unrelated adapters are not replaced. Status separates saved binding, active Gateway binding, transport thread and unprobed connection/delivery health. Durable per-resource control receipts and device journals forbid fresh-nonce retry after uncertain lifecycle.

Incoming provider conversation/message IDs are required, signature-adapted before exactly one callback. Data is deduplicated in existing background_deliveries and appended with explicit channel attribution to the same bot home, never admitted as model/tool work. Global Stop/live-owner checks still apply. Automatic replies are not enabled by connecting. Stop gates active incoming handlers, waits for thread exit before removing matching bridge/adapter, and unsubscribes approval callbacks. Telegram now signals its parked bootstrap and shuts down polling/application on that same loop; iMessage restart clears its stop event; Discord captures its actual loop on ready.

Compatibility: additive schema_meta binding/resource pointers and existing delivery receipts; no new database/schema. New channel_message transcript kind requires current shared UI, which renders it as incoming data. Older UI may mislabel unknown message kinds; do not activate this new path with old UI. Rollback preserves transcripts/metadata/journals and must not replay unresolved operations or provider messages. External SDK/provider delivery and OS permissions remain unqualified; no external activation occurred during implementation.

## Optional channels: Telegram and iMessage (off by default)

Phone reach for Jaeger is **web push to the Jaeger web app** (install it to the
iPhone Home Screen, then turn on notifications in Settings). Replies and Mac
actions happen in the web app on the phone. Telegram and iMessage are optional
extras for operators who want them; each stays off until configured.

| Channel | Turns on when | How to turn on |
| --- | --- | --- |
| Telegram | `JAEGER_TELEGRAM_BOT_TOKEN` is in `~/.jaeger/secrets.env` and `telegram.enabled` is not false | Create a bot with @BotFather (`/newbot`), put the token in `~/.jaeger/secrets.env` (never in chat), restart `com.jenkinsrobotics.jaeger-channels`, then pair your one private chat with the pairing code |
| iMessage | `imessage.self_handles` is set and `imessage.enabled` is true in `~/.jaeger/channels/config.json` | Add your own phone/email handles to `self_handles`, set `send_to` to one of them, set `enabled: true`, restart the channels job. It only reads your 1:1 self-chat and only replies to `send_to` |

With neither configured the relay logs `telegram: off (optional …)` and
`imessage: off (optional …)` and does nothing else on those channels.
