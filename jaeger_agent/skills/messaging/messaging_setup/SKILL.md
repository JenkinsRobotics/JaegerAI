---
name: messaging_setup
description: "Bring a messaging channel (Discord, Telegram, iMessage) live so the agent can send/receive on it. Load this whenever the user wants to 'connect Discord', 'set up Telegram', 'text me on iMessage', asks why a channel isn't working, or asks what's needed to message them somewhere new."
version: 1.0.0
platforms: [linux, macos, windows]
requires_tools: [list_plugins, setup_plugin, set_credential, activate_plugin, send_message]
metadata:
  jros:
    tags: [messaging, discord, telegram, imessage, setup, channels, credentials]
    category: messaging
    related_skills: [scheduling]
---

# MESSAGING SETUP — DISCORD / TELEGRAM / IMESSAGE

Discord, Telegram, and iMessage are module-provided **channels** (not
plugins — `list_plugins()` reports them with `"kind": "channel"`
alongside real plugins, same status vocabulary). Each needs a credential
stored, then an explicit activation before `send_message` can reach it.

## PER-CHANNEL CREDENTIALS

| Channel  | Required credential   | Where to get it                          | Optional |
|----------|------------------------|-------------------------------------------|----------|
| discord  | `DISCORD_BOT_TOKEN`   | Discord Developer Portal -> New Application -> Bot -> Reset Token. Also enable "Message Content Intent" under Bot settings, and invite the bot to the server (OAuth2 URL Generator -> scope `bot`, permission "Send Messages"). | `DISCORD_ALLOWED_USER_IDS` (comma-separated Discord user IDs — unset means open to anyone who can message the bot), `DISCORD_ADMIN_IDS` |
| telegram | `TELEGRAM_BOT_TOKEN`  | Telegram app -> message **@BotFather** -> `/newbot` -> follow the prompts -> it replies with the token. | `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated chat IDs), `TELEGRAM_ADMIN_IDS` |
| imessage | none (no auth token)  | macOS only. Drives Messages.app via AppleScript + reads `chat.db` directly — needs **Full Disk Access** granted to the process running the agent (System Settings -> Privacy & Security -> Full Disk Access). | `IMESSAGE_ALLOWED_HANDLES` (comma-separated phone numbers / Apple IDs — **strongly recommended**, since there's no token to gate who can reach the agent), `IMESSAGE_ADMIN_IDS` |

Credential names are exact — `setup_plugin(name)` echoes back the precise
name each channel needs; never invent or guess one.

## THE FLOW (exact order)

1. **Check availability** — `list_plugins()`, find the row where
   `name` is the channel and `kind == "channel"`. Read `status`:
   `ready` / `needs_install` / `needs_credentials` /
   `needs_install_and_credentials` / `unsupported_on_this_platform`.
   If you need the exact steps, `setup_plugin(name="discord")` (etc.)
   returns a numbered guide plus `library_status`/`env_status`.
2. **Missing a library** — surface the `pip install` command
   `setup_plugin` gives you; a library gap means the channel can't run
   on this box until it's installed (a restart of the agent process is
   needed after installing).
3. **Set the credential** — ask the user for the token/value (NEVER
   invent one), then `set_credential(name="DISCORD_BOT_TOKEN",
   value="...")` (etc., using the exact name from the table above).
4. **Activate** — `activate_plugin(name="discord")`. This connects the
   bridge in a background thread AND persists the channel into this
   instance's autostart list, so it comes back live on every future
   restart without repeating this step. If it reports a missing
   credential, go back to step 3 — never retry with a guessed token.
5. **Send a test message** — `send_message(channel="discord",
   recipient="<id or handle>", text="test — I'm live")` to confirm the
   whole path works end to end. Report success/failure to the user
   plainly.

## TROUBLESHOOTING

- **"send_message says the channel isn't available"** — the bridge
  isn't running in this process. Re-check `list_plugins()` status; if
  `ready`, call `activate_plugin(name=...)` (it may have failed
  silently at boot, e.g. autostart skipped a missing credential — read
  the `error` field it returns).
- **"unknown plugin" / setup_plugin errors** — you typed the wrong
  name. Valid channel names are exactly `discord`, `telegram`,
  `imessage` (lowercase); re-run `list_plugins()` to confirm the exact
  name.
- **Credential set but still `needs_credentials`** — the name didn't
  match exactly (case matters for `set_credential`'s stored key vs.
  what `setup_plugin` names, though lookups are case-insensitive —
  double check for a typo like `DISCORD_TOKEN` instead of
  `DISCORD_BOT_TOKEN`). Re-run `setup_plugin(name=...)` to see the
  current `env_status`.
- **iMessage specifically not working** — three separate gates: (a)
  platform must be macOS (`platform_ok: false` elsewhere means stop —
  it cannot run), (b) Full Disk Access must be granted to the process,
  (c) no allowlist set means it accepts messages from ANYONE with the
  recipient's contact info — set `IMESSAGE_ALLOWED_HANDLES` unless the
  user explicitly wants it open.
- **Discord bot online but not responding** — "Message Content Intent"
  is commonly forgotten in the Developer Portal; without it the bot
  can't read message text at all.
- **Telegram bot not responding in a group** — BotFather bots default
  to privacy mode (only see commands, not plain messages, in groups);
  `/setprivacy` -> disable via BotFather, or only rely on DMs.

## DONE WHEN

`list_plugins()` shows the channel `status: "ready"`, `activate_plugin`
returned `{"started": true, ...}`, and a real `send_message` round-trip
reached the user (or they confirmed receiving it) — never claim a
channel is live from `set_credential` succeeding alone.
