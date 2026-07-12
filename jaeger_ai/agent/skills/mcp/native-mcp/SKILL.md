---
name: native-mcp
description: "Wire external MCP servers (stdio or HTTP) into Hermes so their tools auto-load every session. Load this when the user wants to add MCP-provided capabilities (filesystem, GitHub, databases, remote APIs) as first-class agent tools, or is debugging why MCP tools don't appear."
version: 1.1.0
platforms: [macos, linux, windows]
requires_tools: [read_file, write_file, patch, terminal]
metadata:
  jros:
    tags: [mcp, tools, integrations, config, stdio, http]
    category: mcp
    related_skills: [hermes-agent]
---

# NATIVE MCP CLIENT

Hermes has a built-in MCP client. It reads server definitions from
`~/.hermes/config.yaml`, connects at startup, discovers each server's tools, and
registers them as first-class agent tools named `mcp_{server}_{tool}`. No bridge
CLI. For one-off ad-hoc MCP calls without config, use the `mcporter` skill instead.

## TOOLS (call these)

- `read_file(path="~/.hermes/config.yaml")` — inspect current server config.
- `patch(path=..., ...)` — add/edit one `mcp_servers` entry in place.
- `write_file(...)` — only when creating the config from scratch.
- `terminal(command="pip install mcp")` — install the SDK; also `terminal` to
  restart the agent so new servers connect.

## PREREQUISITES

- `mcp` Python package — `terminal(command="pip install mcp")`. If missing, MCP
  support is silently disabled (see error hatch).
- `node`/`npx` for community npx servers; `uv`/`uvx` for Python servers.

## SOP — ADD A SERVER

1. `read_file("~/.hermes/config.yaml")`. Find or create the top-level
   `mcp_servers:` key.
2. Add ONE entry using stdio OR http (never both) — see CONFIG below.
3. Save with `patch` (preferred) or `write_file`.
4. Restart the agent via `terminal` — servers connect only at startup (no
   hot-reload). Adding/removing a server always needs a restart.
5. Confirm tools appear under the `mcp_{server}_{tool}` prefix and use them.

## CONFIG

Stdio (command-based, most common):
```yaml
mcp_servers:
  filesystem:
    command: "npx"                 # required
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/docs"]
    env:                           # optional; ONLY these vars reach the subprocess
      GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_..."
    timeout: 120                   # per-call seconds (default 120)
    connect_timeout: 60            # startup seconds (default 60)
```

HTTP (remote/shared):
```yaml
mcp_servers:
  remote_api:
    url: "https://mcp.example.com/mcp"   # required
    headers:
      Authorization: "Bearer sk-..."
    timeout: 180
```

Security: stdio subprocesses inherit only a safe baseline env (`PATH HOME USER
LANG LC_ALL TERM SHELL TMPDIR XDG_*`). Secrets reach a server ONLY if you list
them under that server's `env`. Credential-like strings in error messages are
auto-redacted.

## TOOL NAMING

`mcp_{server_name}_{tool_name}`; hyphens/dots become underscores.
- server `github`, tool `list-issues` → `mcp_github_list_issues`.

## SAMPLING (server-initiated LLM calls)

Enabled by default. A server can request completions during tool execution. Tune
per server under a `sampling:` block (`enabled`, `model`, `max_tokens_cap`,
`timeout`, `max_rpm`, `max_tool_rounds`). Set `sampling: { enabled: false }` for
untrusted servers.

## ERROR HATCH

- "MCP SDK not available" → `terminal(command="pip install mcp")`, restart.
- "Failed to connect to 'X'" → command not on PATH, npm package needs `-y`, or
  bump `connect_timeout`. For HTTP, the URL is unreachable.
- HTTP server ImportError (`mcp.client.streamable_http`) →
  `terminal(command="pip install --upgrade mcp")`.
- Tools don't appear → key must be `mcp_servers` (not `mcp`/`servers`), YAML
  indentation valid, and you MUST restart. If it still fails twice, `read_file`
  the startup logs under `~/.hermes/logs/` for the connection error.

## DONE WHEN

The target server is under `mcp_servers` in `~/.hermes/config.yaml`, the agent has
been restarted, and its `mcp_{server}_{tool}` tools are callable in-session.
