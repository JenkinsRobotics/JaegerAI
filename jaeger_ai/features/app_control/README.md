# app_control

Status, start/stop/restart, config reads/edits and built-in invocation (`codex exec`, `claude -p`,
`gemini -p`) for Matthew's agent apps and Jaeger's own launchd services.

- **Proposals only.** Agents (MCP: `jaeger.apps_list`, `jaeger.app_status`, `jaeger.app_action`,
  `jaeger.app_config_get`, `jaeger.app_config_propose`) can read and *propose*. Nothing is applied
  until Matthew approves in the WebUI Machine tab › Agent Apps. Decisions are accepted only from the
  `webui`/`menubar` callers; no MCP apply tool exists.
- **Config edits:** per-app allow-listed keys, backup + `ROLLBACK.sh` under
  `<state>/app_control/backups/`, parse check with automatic rollback, refused while an app that
  rewrites the file is running, vendor CLI (`claude mcp`) where the file is app-managed.
- **Reads are redacted** (tokens, keys, headers, env).
- Opaque apps (Muse, Gemini desktop, HomeClaw, SAM, CuaDriver) get status/start/stop only;
  CuaDriver invoke is disabled (screen control).

Design: `~/Documents/Jaeger-App-Control-Design-2026-10-31.md`. Tests:
`dev/tests/jaeger_ai/features/app_control/` (fake host; never touches a real app).
