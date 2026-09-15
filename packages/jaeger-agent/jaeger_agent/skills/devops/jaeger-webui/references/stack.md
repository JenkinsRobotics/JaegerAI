# Jaeger stack digest (durable — not chat memory)

The operator-facing chat URL is the Mac's **Tailscale IPv4 on port 8790**,
from `jaeger webui url` or `tailscale ip -4` (currently
`http://100.74.2.15:8790/`). Never send the user to `127.0.0.1` — that is a
different browser origin (separate cache / service worker) and is only for
local probes on the Mac. The Hermes container on **8787** is a runtime, not
a chat bookmark. Adapter **8791** is the runner every chat POST hits.

## Ports

| Surface | Port | What "up" means |
| --- | ---: | --- |
| Jaeger WebUI (browser) | 8790 | Title `Jaeger`, identity match, composer usable |
| Hermes WebUI adapter | 8791 | `GET /health` JSON `ok: true` |
| Hermes container UI | 8787 | Optional; NOT the chat bookmark |
| Instance webhooks | 8793 | Must not collide with 8791 |
| Jaeger MCP HTTP | 8792 | MCP backend |
| Agentgateway MCP | 8811 | Public MCP |
| Agentgateway A2A | 8812 | Public A2A |

Launchd labels (KeepAlive): `com.jenkinsrobotics.jaeger-webui`,
`com.jenkinsrobotics.jaeger-hermes-webui-adapter`,
`com.jenkinsrobotics.jaeger-gateway` (`:8810`). A python process listening
on 8810 is not enough — `launchctl print gui/$UID/com.jenkinsrobotics.jaeger-gateway`
must find the job. "Could not find service" means an orphan: kill the
listener, `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.jenkinsrobotics.jaeger-gateway.plist`.
`jaeger webui status` pid files can say stopped while launchd is serving —
check the port.

Gateway `/health` can show every check green with
`webui.chat_execution_verified: false`. That is process-up, not a working
Safari tab. The operator-facing origin is Tailscale (`jaeger webui url`).
Safari `hermes_profile=hermes` lists 0 sessions; the real chats are
`hermes_profile=jaeger`.

## Identity (product-up, not process-up)

The page stamps `window.__HERMES_WEBUI_BUNDLE_VERSION__` from the HTML
shell. `/api/settings` returns `webui_version` from `git describe`.
`checkWebUIVersionSkew` does string equality. If they differ, the UI
shows: "This tab is running a different WebUI version. Hard refresh to
restore full functionality." That banner is a **break**, not a hint.

Do not confuse these clocks:

- served bundle / `settings.webui_version` — must match (product identity)
- `/api/updates/check` `current_version` (e.g. `v0.52.113`) — release tag
  used by the updater; it is allowed to differ from git-describe
- `update_channel_version` — display badge only

A cache-bust suffix belongs on `?v=` asset URLs and the service-worker
cache name, **never** on `__HERMES_WEBUI_BUNDLE_VERSION__`.

## Probe (copy/paste)

Chat URL is Tailscale, not loopback. Resolve it first:

```
CHAT=$(jaeger webui url)   # e.g. http://100.74.2.15:8790/
curl -sS -D- -o /tmp/webui.html -m 5 "$CHAT"
curl -sS -m 5 "${CHAT%/}/api/settings" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('webui_version'))"
python3 -c "import re,pathlib; t=pathlib.Path('/tmp/webui.html').read_text(); print(re.search(r\"__HERMES_WEBUI_BUNDLE_VERSION__='([^']+)'\",t).group(1))"
curl -sS -m 5 http://127.0.0.1:8791/health
```

On the Mac, loopback `:8790` is an allowed *local* health probe. It is not
the URL to give the user. Shell title must be `Jaeger`. Bundle string must
equal `webui_version`. Adapter health must be `ok: true`. Then snapshot
`$CHAT` with `browser` (never `open_on_host`).

Source of truth for the public port map: repo `README.md` (Jaeger WebUI
section). This file is the ops digest the agent should load.
