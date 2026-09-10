# Channels — port notes

## Donors (read-only)

| Donor | Paths | Steal |
|---|---|---|
| openclaw | `src/channels/*` (catalog, allow-from, ack-reactions, chat-type) | Catalog contract, allowlists, conversation labeling |
| openclaw | `src/auto-reply/*` | Command gating / turn-context patterns |
| openclaw | `extensions/{whatsapp,signal,matrix,feishu,line,irc,googlechat,msteams}/` | One platform at a time |
| hermes-agent | `gateway/platforms/`, `plugins/platforms/`, `gateway/pairing.py` | Python-native pairing store if staying in-process |

## Landed this depth pass

- `PluginBridgeAdapter` + `register_plugin_bridge` wrap live Discord/Telegram/iMessage bridges
- `messaging_gateway` registers started plugins onto `ChannelRegistry`

## First follow-up slices (do not block this commit)

1. Pairing store (`features/channels/pairing/`) — DM allow codes; Hermes `pairing.py` + OpenClaw allow-from.
2. WhatsApp **or** Signal thin adapter implementing `ChannelAdapter`.
3. Wire catalog into WebUI / CLI `jaeger channels list`.

## Explicitly later

- Device/node QR pairing (`openclaw/src/pairing`, `extensions/device-pair`) — Maybe; do not block channels ingress.
- Running OpenClaw gateway as a second control plane — Skip.
