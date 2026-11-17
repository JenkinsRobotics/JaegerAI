---
name: native-mcp
description: Jaeger connectors (MCP servers): list what is connected, add a new stdio or HTTP
  MCP server, or debug why its tools are missing. Load this when the user asks what connectors
  or MCP servers you have, whether GitHub (or any service) is connected, or how to add one.
metadata:
  jros:
    tags: [mcp, connectors, tools, integrations, github]
    category: mcp
    version: 2.0.0
---

# Jaeger connectors (MCP servers)

**Never answer from memory or from a Hermes config.** Jaeger does not use `~/.hermes/config.yaml`.

## What is connected
Call `list_connectors`. It returns each server's name, transport, status (active / configured /
error / disabled), tool count, and whether it starts with the Gateway. The config file is
`~/.jaeger/instances/<instance>/mcp.json`.

Current built-ins on Matthew's Mac: `github` (official github-mcp-server, read-only, auth from
`gh`), `rea` (reverse engineering), `jaeger-mac`.

Connector tools are gated. Find them with `tool_search "github pull requests"` or
`load_tools`, then call `mcp__<server>__<tool>`, e.g. `mcp__github__list_pull_requests`.

## Add a new one (hot, no restart)
Call `add_connector(name, command=..., args=[...])` for a stdio server, or
`add_connector(name, url=...)` for an HTTP server. Examples:
- `add_connector("everything", command="npx", args=["-y", "@modelcontextprotocol/server-everything"])`
- `add_connector("fetch", command="uvx", args=["mcp-server-fetch"])`

It runs the reviewed path: the server is staged disabled, credentials are refused, then it is
enabled with `"gateway": true` and connected in-process. The reply lists the new tools.

**Servers that need a token:** never put the token in the call or in mcp.json. Write a launcher
script that reads the token at runtime (for example from `gh auth token` or the Keychain), and
point `command` at it. See `scripts/connectors/github-mcp.sh`.

How a user adds one by hand: tell Jaeger "add the X MCP server" in chat, or append a row to
mcp.json (`{"name","command","args","enabled":true,"gateway":true}`) and restart the gateway
(`launchctl kickstart -k gui/$UID/com.jenkinsrobotics.jaeger-gateway`).

## Tools missing?
- `list_connectors` shows `error`: read the error field. Usually the command isn't on PATH
  (use an absolute path) or auth failed.
- Status `configured` but 0 tools: the server is not marked `gateway`, or it connected before
  the change. A gateway restart fixes it.
- Untrusted servers: keep them gated and read-only; do not add any server that asks for model
  sampling.
