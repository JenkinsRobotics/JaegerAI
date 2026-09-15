# Personal Finance

Connects to Monarch Money to read accounts, balances, transactions and budgets,
and runs a background worker that keeps the local copy fresh.

| File | What it does |
| :--- | :--- |
| `monarch_service.py` | All Monarch API calls and the login session. |
| `finance_worker.py` | Background refresh on a schedule. |
| `mission_finance.py` | Longer-running finance jobs (audits, reviews). |
| `tools.py` | `finance_summary`, `finance_audit`, `finance_transactions`. |

**Turn it on:** log in once; the session is cached under your state directory
(`JAEGER_STATE_DIR`, default `~/.jaeger`), never in this folder.

**Check it works:** ask for a finance summary. An expired login returns a
`MonarchError` telling you to sign in again.

---

*Every folder under `jaeger_ai/features/` follows this shape: `service.py` or
`store.py` holds the logic, `tools.py` (when present) exposes it to the agent as
callable tools, and `__init__.py` lists what the rest of Jaeger is allowed to
import. Tools are registered in `jaeger_ai/main.py` and surfaced over MCP by
`jaeger_ai/interfaces/mcp_server.py`.*
