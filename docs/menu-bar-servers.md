# Menu-bar server controls

Open the Jaeger menu-bar icon, then **Servers**. The section shows Gateway,
Jaeger Agent, Hermes, OpenClaw, Chat Runner and Web UI. Each row has a menu for
Start, Stop and Restart. Start All brings up the configured services without
restarting jobs that are already running. Stop All stops them in reverse order.
The globe button opens the deployment-resolved Web UI address.

Controls invoke `jaeger webui servers` locally, so the gateway need not be
available to recover it. Launchd services use their existing per-user plists.
Stop unloads the job, rather than killing a process that KeepAlive would respawn.
Hermes controls include its container and native API supervisor. No services are
installed implicitly. Failed commands remain visible in the menu.

CLI equivalents:

```
jaeger webui servers status
jaeger webui servers start all
jaeger webui servers restart webui
jaeger webui servers stop hermes
```

Stopping/restarting interrupts active chats. A listening gateway can still show
Not ready when its `/health` endpoint returns a dependency error; the menu does
not disguise a failed health check as success.

Validation: native Swift app compiled and code-signature verified; lifecycle
unit tests mock every system action; Start All exercised against the local
services without restarting active jobs.

# Browser freeze repair

The branding extension's assistant-label MutationObserver rewrote the same DOM
attributes and text on every notification. Its own writes generated another
notification indefinitely, starving browser input and streaming callbacks after
an assistant response. Identity updates now write only changed values, and boot
registration runs once. A real Chromium fixture verifies mutations settle and
later identity changes still render. A real browser also loaded the affected
session, sent a new chat, and completed a follow-up without losing composer
responsiveness. Existing frozen tabs need a reload to load the repaired script.

## MCP instance binding

The installed `com.jenkinsrobotics.jaeger-mcp-http` LaunchAgent must launch
`jaeger_ai.interfaces.mcp_server --http --instance jaeger` for this deployment.
Without the explicit instance, it can retain a previous active test instance
for its entire lifetime. The gateway correctly reports that disconnected
backend as unhealthy even when the real Jaeger bridge is ready. The installed
plist was corrected and only MCP HTTP was reloaded; gateway `/health` then
returned HTTP 200 with `all_green: true` and all six menu services Ready.
