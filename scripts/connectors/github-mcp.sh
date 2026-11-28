#!/bin/zsh
# Jaeger's GitHub connector (P10): the official GitHub MCP server, read-only.
# Auth comes from the local user's existing `gh` login at launch; the token is never
# written to disk or config and never printed.
set -eu
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
GITHUB_PERSONAL_ACCESS_TOKEN="$(gh auth token 2>/dev/null)" || { print -u2 "gh is not logged in"; exit 1; }
export GITHUB_PERSONAL_ACCESS_TOKEN
exec github-mcp-server stdio --read-only --toolsets repos,issues,pull_requests,actions,context
