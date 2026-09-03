# ARES feature absorption map

**Updated:** 2026-09-03

JaegerAI is authoritative. ARES remains unchanged as a rollback reference until
the ADR-0012 retirement gates pass. A documentation claim does not count as
parity; each row below points to executable Jaeger code.

| ARES capability | Jaeger owner | Status |
|---|---|---|
| Worker health and effectiveness ranking | `jaeger_agent/delegates/health`, `delegates/routing` | Implemented |
| Claude, Codex, Grok, Gemini, OpenCode, Cursor, Ollama, OpenClaw, Hermes adapters | One folder per runtime under `jaeger_agent/delegates` | Implemented |
| Mission, goal, plan management | `jaeger_ai/features/missions` + cognitive commitments/runs | Implemented |
| Kanban dispatch | `jaeger_agent/tools/kanban.py`, `background/board.py` | Existing parity |
| Scheduled jobs and delivery | `background/cron.py`, `core/runtime/schedules.py`, `cron_delivery.py` | Existing parity |
| Knowledge graph | `memory/sqlite_knowledge.py` | Existing parity |
| Notes, libraries, document indexing | `jaeger_ai/features/knowledge_library` | Implemented for safe local text corpora |
| Unified CLI and ARES history | `jaeger_ai/features/history_import/<source>` | Implemented for ARES, Claude, Codex, Gemini, Grok |
| Deep research | web-research skills + Deep Think + ranked external delegates | Existing/composed parity |
| Budget, usage, costs | `jaeger_ai/features/cost_tracking` | Implemented; delegate admission integrated |
| API authentication and network trust | `features/remote_access`, `features/oidc`, `features/passkeys` | Bearer, signed sessions, OIDC+PKCE, WebAuthn, and trusted-network enforcement implemented |
| Tailscale remote portal | Hermes WebUI adapter `--allow-remote` | Implemented, default off |
| Email and native calendar | `jaeger_agent/tools/email.py`, `tools/calendar.py` | Existing native macOS parity |
| Generic CalDAV accounts | `jaeger_ai/features/caldav` | Implemented with instance-scoped secrets and bounded HTTP/XML handling |
| Worktree and workspace management | `subagent_worktree.py`, `workspace.py` | Existing parity |
| Rollback, backup, update, crash recovery | CLI backup/update modules + durable run recovery | Existing parity |
| Native macOS menu app and MCP | PySide/Swift interfaces + MCP plugin | Existing parity |
| Hermes WebUI | `interfaces/hermes_webui_adapter` | Implemented and explicitly named |
| OIDC and passkeys | `jaeger_ai/features/oidc`, `features/passkeys` | Implemented as separate features and exposed by the Hermes WebUI adapter |
| Insta360 hardware | `jaeger_ai/features/insta360` | Implemented with AVFoundation media and native IOKit PTZ |
| ARES state migration and retirement rehearsal | `jaeger_ai/features/ares_migration` | Implemented; deliberately non-destructive and operator-triggered |

“Existing parity” means executable code was present in Jaeger before this
absorption change and was code-audited, not inferred from documentation.
“Implemented” means executable code and focused tests exist. It does not mean
the operator's live ARES state has been migrated or that ARES may be removed;
the ADR retirement gates still apply.
