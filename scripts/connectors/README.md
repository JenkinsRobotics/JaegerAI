# Connector launchers

`github-mcp.sh` starts the official GitHub MCP server (`brew install github-mcp-server`)
in read-only mode. It reads auth from the existing `gh auth login` at launch, so no token
lands in `mcp.json` or on disk.

Install it as a connector:

1. `brew install github-mcp-server gh && gh auth login`
2. Copy it to `~/.jaeger/bin/github-mcp` (mode 700).
3. Stage it disabled, then enable it, either from Settings → Connectors or with
   `jaeger_ai.core.mcp.service.stage_disabled_server` and `set_startup_enabled`.
   Then set `"gateway": true` on the row so the Gateway connects to it at startup.
4. Restart the gateway: `launchctl kickstart -k gui/$UID/com.jenkinsrobotics.jaeger-gateway`.

Tools show up as `mcp__github__*`. They are gated and load on demand through tool_search/load_tools.

## Read-only approval

The server runs with `--read-only`, so declare its tools read-only in the instance `mcp.json` (`"tools": {"read_only": ["*"]}` on the `github` entry). Otherwise every call asks for approval, and the call is refused when nobody is there to answer.
